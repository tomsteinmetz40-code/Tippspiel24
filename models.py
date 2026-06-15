"""
SQLAlchemy ORM models for Tippspiel24.

Schema mirrors the original SQLite tables so that all existing
template/route logic continues to work unchanged.
"""

from database import db


class Spiel(db.Model):
    __tablename__ = "spiele"

    id        = db.Column(db.Integer,  primary_key=True, autoincrement=True)
    team_heim = db.Column(db.String(100), nullable=False)
    team_gast = db.Column(db.String(100), nullable=False)
    anstoss   = db.Column(db.String(32),  nullable=False)
    tore_heim = db.Column(db.Integer,  nullable=True)
    tore_gast = db.Column(db.Integer,  nullable=True)

    tipps = db.relationship("Tipp", back_populates="spiel",
                            cascade="all, delete-orphan", passive_deletes=True)

    def __getitem__(self, key):
        return getattr(self, key)

    def keys(self):
        return ["id", "team_heim", "team_gast", "anstoss", "tore_heim", "tore_gast"]


class Klasse(db.Model):
    __tablename__ = "klassen"

    id   = db.Column(db.Integer,     primary_key=True, autoincrement=True)
    name = db.Column(db.String(100), nullable=False, unique=True)

    def __getitem__(self, key):
        return getattr(self, key)

    def keys(self):
        return ["id", "name"]


class Tipp(db.Model):
    __tablename__ = "tipps"
    __table_args__ = (
        db.UniqueConstraint("spiel_id", "spieler", name="uq_tipp_spiel_spieler"),
    )

    id        = db.Column(db.Integer, primary_key=True, autoincrement=True)
    spiel_id  = db.Column(db.Integer, db.ForeignKey("spiele.id", ondelete="CASCADE"),
                          nullable=False)
    spieler   = db.Column(db.String(200), nullable=False)
    klasse    = db.Column(db.String(100), nullable=True)
    tipp_heim = db.Column(db.Integer, nullable=False)
    tipp_gast = db.Column(db.Integer, nullable=False)
    abgegeben = db.Column(db.String(32),  nullable=False)

    spiel = db.relationship("Spiel", back_populates="tipps")

    def __getitem__(self, key):
        return getattr(self, key)

    def keys(self):
        return ["id", "spiel_id", "spieler", "klasse",
                "tipp_heim", "tipp_gast", "abgegeben"]


class AdminLogin(db.Model):
    __tablename__ = "admin_logins"

    name          = db.Column(db.String(200), primary_key=True)
    rolle         = db.Column(db.String(20),  nullable=False)
    gesperrt      = db.Column(db.Integer,     nullable=False, default=0)
    letzter_login = db.Column(db.String(32),  nullable=True)

    def __getitem__(self, key):
        return getattr(self, key)

    def keys(self):
        return ["name", "rolle", "gesperrt", "letzter_login"]


class Spieler(db.Model):
    __tablename__ = "spieler"

    name   = db.Column(db.String(200), primary_key=True)
    klasse = db.Column(db.String(100), nullable=True)
    pin    = db.Column(db.String(10),  nullable=False, unique=True)

    def __getitem__(self, key):
        return getattr(self, key)

    def keys(self):
        return ["name", "klasse", "pin"]
