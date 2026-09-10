"""Schema unico em SQLAlchemy — SQLite no piloto, PostgreSQL sem reescrita.

Tres regras estruturais, herdadas do documento de decisao:

1. `raw_document` e imutavel: todo arquivo ou resposta que entrou no sistema fica
   gravado como veio, com hash e `sync_run_id`. Recalculo nunca depende de nova coleta.
2. A chave de pessoa e o ID Lattes (TEXT, nunca inteiro — pode comecar com zero).
3. Cada ponto do indice tera uma linha em `score_component` apontando o item de
   producao, a regra que o converteu e o documento bruto de onde veio.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, relationship


def agora() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


# --------------------------------------------------------------------------- #
# Auditoria de coleta
# --------------------------------------------------------------------------- #
class SyncRun(Base):
    """Uma execucao de conector. Sem isto nao ha como explicar por que o numero
    de ontem mudou hoje."""

    __tablename__ = "sync_run"

    id = Column(Integer, primary_key=True)
    source = Column(String(40), nullable=False, index=True)
    params = Column(Text)
    started_at = Column(DateTime, nullable=False, default=agora)
    finished_at = Column(DateTime)
    status = Column(String(16), nullable=False, default="running")  # running|ok|erro
    n_documents = Column(Integer, default=0)
    error = Column(Text)


class RawDocument(Base):
    """Todo dado coletado, gravado como veio."""

    __tablename__ = "raw_document"
    __table_args__ = (UniqueConstraint("source", "source_ref", "content_hash"),)

    id = Column(Integer, primary_key=True)
    source = Column(String(40), nullable=False, index=True)
    source_ref = Column(String(300), nullable=False)
    sync_run_id = Column(Integer, ForeignKey("sync_run.id"), nullable=False)
    collected_at = Column(DateTime, nullable=False, default=agora)
    content_hash = Column(String(64), nullable=False, index=True)
    media_type = Column(String(40), default="application/json")
    path = Column(String(500), nullable=False)


# --------------------------------------------------------------------------- #
# Pessoas e vinculos
# --------------------------------------------------------------------------- #
class Faculty(Base):
    __tablename__ = "faculty"

    id = Column(Integer, primary_key=True)
    full_name = Column(String(300), nullable=False)
    display_name = Column(String(300))
    lattes_id = Column(String(20), unique=True, index=True)  # TEXT: pode ter zero a esquerda
    orcid = Column(String(25), index=True)
    brcris_id = Column(String(80), index=True)
    curriculo_atualizado_em = Column(Date)
    created_at = Column(DateTime, default=agora)

    identifiers = relationship("FacultyIdentifier", back_populates="faculty",
                               cascade="all, delete-orphan")
    citation_names = relationship("CitationName", back_populates="faculty",
                                  cascade="all, delete-orphan")
    memberships = relationship("Membership", back_populates="faculty",
                               cascade="all, delete-orphan")


class FacultyIdentifier(Base):
    __tablename__ = "faculty_identifier"
    __table_args__ = (UniqueConstraint("faculty_id", "kind", "value"),)

    id = Column(Integer, primary_key=True)
    faculty_id = Column(Integer, ForeignKey("faculty.id"), nullable=False)
    kind = Column(String(20), nullable=False)  # lattes|orcid|brcris|openalex|scopus|siape
    value = Column(String(120), nullable=False)
    verified_at = Column(DateTime, default=agora)
    source = Column(String(40))

    faculty = relationship("Faculty", back_populates="identifiers")


class CitationName(Base):
    """Variacoes de assinatura. Insumo para casar autoria em bases externas."""

    __tablename__ = "citation_name"
    __table_args__ = (UniqueConstraint("faculty_id", "name"),)

    id = Column(Integer, primary_key=True)
    faculty_id = Column(Integer, ForeignKey("faculty.id"), nullable=False)
    name = Column(String(200), nullable=False)
    source = Column(String(40))

    faculty = relationship("Faculty", back_populates="citation_names")


class PPG(Base):
    __tablename__ = "ppg"

    id = Column(Integer, primary_key=True)
    sigla = Column(String(40), unique=True, nullable=False)
    nome = Column(String(300), nullable=False)
    codigo_capes = Column(String(20), index=True)
    area_capes = Column(String(120))
    niveis = Column(String(120))  # mestrado|doutorado|mestrado,doutorado

    memberships = relationship("Membership", back_populates="ppg")


class MembershipSnapshot(Base):
    """Foto da lista de docentes de um PPG numa coleta."""

    __tablename__ = "membership_snapshot"

    id = Column(Integer, primary_key=True)
    ppg_id = Column(Integer, ForeignKey("ppg.id"), nullable=False)
    sync_run_id = Column(Integer, ForeignKey("sync_run.id"), nullable=False)
    collected_at = Column(DateTime, default=agora)
    fonte = Column(String(60), nullable=False)  # secretaria|capes_aberto|site_ppg
    n_docentes = Column(Integer, default=0)


class Membership(Base):
    """Vinculo docente↔PPG. Nunca vem do BrCris — so da secretaria ou da CAPES."""

    __tablename__ = "membership"
    __table_args__ = (UniqueConstraint("faculty_id", "ppg_id", "snapshot_id"),)

    id = Column(Integer, primary_key=True)
    faculty_id = Column(Integer, ForeignKey("faculty.id"), nullable=False)
    ppg_id = Column(Integer, ForeignKey("ppg.id"), nullable=False)
    snapshot_id = Column(Integer, ForeignKey("membership_snapshot.id"))
    categoria = Column(String(20))  # permanente|colaborador|visitante
    inicio = Column(Integer)
    fim = Column(Integer)
    fonte = Column(String(60), nullable=False)

    faculty = relationship("Faculty", back_populates="memberships")
    ppg = relationship("PPG", back_populates="memberships")


# --------------------------------------------------------------------------- #
# Obras
# --------------------------------------------------------------------------- #
class Journal(Base):
    __tablename__ = "journal"

    id = Column(Integer, primary_key=True)
    titulo = Column(String(400))
    issn = Column(String(9), index=True)
    issn_l = Column(String(9), index=True)
    area_capes = Column(String(120))
    brcris_id = Column(String(80), index=True)


class Work(Base):
    __tablename__ = "work"

    id = Column(Integer, primary_key=True)
    titulo = Column(Text, nullable=False)
    titulo_normalizado = Column(Text, index=True)
    tipo = Column(String(40), index=True)  # artigo|evento|capitulo|livro|preprint|tese
    ano = Column(Integer, index=True)
    data_publicacao_bruta = Column(String(200))
    ano_ambiguo = Column(Boolean, default=False)
    doi = Column(String(200), index=True)
    issn = Column(String(9), index=True)
    journal_id = Column(Integer, ForeignKey("journal.id"))
    volume = Column(String(40))
    pagina_inicial = Column(String(20))
    fonte = Column(String(40), nullable=False, index=True)
    fonte_ref = Column(String(200), index=True)
    raw_document_id = Column(Integer, ForeignKey("raw_document.id"))
    resolvido_por = Column(String(20))  # doi|issn_ano|titulo|nenhum
    criado_em = Column(DateTime, default=agora)

    journal = relationship("Journal")
    authorships = relationship("Authorship", back_populates="work",
                               cascade="all, delete-orphan")
    bibliometria = relationship("Bibliometrics", back_populates="work",
                                uselist=False, cascade="all, delete-orphan")


Index("ix_work_doi_unico", Work.doi, unique=True, sqlite_where=Work.doi.isnot(None))


class Authorship(Base):
    __tablename__ = "authorship"
    __table_args__ = (UniqueConstraint("work_id", "faculty_id"),)

    id = Column(Integer, primary_key=True)
    work_id = Column(Integer, ForeignKey("work.id"), nullable=False)
    faculty_id = Column(Integer, ForeignKey("faculty.id"), nullable=False)
    posicao = Column(Integer)
    nome_assinatura = Column(String(200))
    fonte = Column(String(40))

    work = relationship("Work", back_populates="authorships")
    faculty = relationship("Faculty")


class Bibliometrics(Base):
    __tablename__ = "bibliometrics"

    id = Column(Integer, primary_key=True)
    work_id = Column(Integer, ForeignKey("work.id"), nullable=False, unique=True)
    openalex_id = Column(String(60), index=True)
    citacoes = Column(Integer)
    percentil_area = Column(Float)
    coautoria_estrangeira = Column(Boolean)
    paises = Column(String(300))
    fonte = Column(String(40))
    coletado_em = Column(DateTime, default=agora)

    work = relationship("Work", back_populates="bibliometria")


class WorkMatchDecision(Base):
    """Nenhum merge fica sem autor responsavel."""

    __tablename__ = "work_match_decision"

    id = Column(Integer, primary_key=True)
    work_a = Column(Integer, ForeignKey("work.id"), nullable=False)
    work_b = Column(Integer, ForeignKey("work.id"), nullable=False)
    metodo = Column(String(20), nullable=False)  # doi|issn_ano_pagina|titulo_ano
    escore = Column(Float)
    decisao = Column(String(16), nullable=False)  # merge|distinto|pendente
    decidido_por = Column(String(80))
    decidido_em = Column(DateTime, default=agora)


# --------------------------------------------------------------------------- #
# Formacao e producao tecnica
# --------------------------------------------------------------------------- #
class Orientation(Base):
    __tablename__ = "orientation"

    id = Column(Integer, primary_key=True)
    faculty_id = Column(Integer, ForeignKey("faculty.id"), nullable=False)
    orientando = Column(String(300))
    nivel = Column(String(30), index=True)  # mestrado|doutorado|iniciacao|pos_doutorado
    papel = Column(String(20), default="orientacao")  # orientacao|coorientacao
    ano = Column(Integer, index=True)
    situacao = Column(String(20))  # concluida|andamento
    ppg_id = Column(Integer, ForeignKey("ppg.id"))
    fonte = Column(String(40))
    fonte_ref = Column(String(200))

    faculty = relationship("Faculty")


class TechnicalOutput(Base):
    """Producao tecnica e tecnologica — patentes, software, registros."""

    __tablename__ = "technical_output"

    id = Column(Integer, primary_key=True)
    faculty_id = Column(Integer, ForeignKey("faculty.id"), nullable=False)
    tipo = Column(String(30), index=True)  # patente|software|cultivar|marca
    titulo = Column(Text)
    ano = Column(Integer)
    situacao = Column(String(30))  # depositada|concedida|registrado
    numero = Column(String(80))
    fonte = Column(String(40))
    fonte_ref = Column(String(200))

    faculty = relationship("Faculty")


# --------------------------------------------------------------------------- #
# Qualis e indicadores
# --------------------------------------------------------------------------- #
class QualisStratum(Base):
    __tablename__ = "qualis_stratum"
    __table_args__ = (UniqueConstraint("ciclo", "area_capes", "issn"),)

    id = Column(Integer, primary_key=True)
    ciclo = Column(String(20), nullable=False)
    area_capes = Column(String(120), nullable=False)
    issn = Column(String(9), nullable=False, index=True)
    titulo_periodico = Column(String(400))
    estrato = Column(String(4), nullable=False)


class MetricSnapshot(Base):
    """Indicadores intermediarios (Q, F, R, T, I) materializados."""

    __tablename__ = "metric_snapshot"
    __table_args__ = (UniqueConstraint("faculty_id", "ppg_id", "periodo", "metrica",
                                       "rule_version"),)

    id = Column(Integer, primary_key=True)
    faculty_id = Column(Integer, ForeignKey("faculty.id"), nullable=False)
    ppg_id = Column(Integer, ForeignKey("ppg.id"))
    periodo = Column(String(20), nullable=False)
    metrica = Column(String(10), nullable=False)
    valor = Column(Float)
    calculado_em = Column(DateTime, default=agora)
    rule_version = Column(String(40))


class FacultyScore(Base):
    __tablename__ = "faculty_score"
    __table_args__ = (UniqueConstraint("faculty_id", "ppg_id", "periodo", "rule_version"),)

    id = Column(Integer, primary_key=True)
    faculty_id = Column(Integer, ForeignKey("faculty.id"), nullable=False)
    ppg_id = Column(Integer, ForeignKey("ppg.id"))
    periodo = Column(String(20), nullable=False)
    rule_version = Column(String(40), nullable=False)
    ipd = Column(Float)
    calculado_em = Column(DateTime, default=agora)


class ScoreComponent(Base):
    """O coracao da defensibilidade: cada ponto do IPD tem uma linha aqui."""

    __tablename__ = "score_component"

    id = Column(Integer, primary_key=True)
    faculty_score_id = Column(Integer, ForeignKey("faculty_score.id"), nullable=False)
    dimensao = Column(String(4), nullable=False)
    item_type = Column(String(30), nullable=False)
    item_id = Column(Integer)
    valor_bruto = Column(Float)
    peso_aplicado = Column(Float)
    pontos = Column(Float)
    regra_ref = Column(String(120))
    fonte = Column(String(40))
    raw_document_id = Column(Integer, ForeignKey("raw_document.id"))
