import os
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


def _build_uri():
    """
    Prefer DATABASE_URL if set, otherwise assemble from individual vars.
    PyMySQL requires the scheme 'mysql+pymysql://'.
    """
    url = os.getenv("DATABASE_URL")
    if url:
        # Railway sometimes provides 'mysql://' – normalise to pymysql driver
        if url.startswith("mysql://"):
            url = "mysql+pymysql://" + url[len("mysql://"):]
        return url

    host     = os.getenv("DB_HOST",     "localhost")
    port     = os.getenv("DB_PORT",     "3306")
    user     = os.getenv("DB_USER",     "root")
    password = os.getenv("DB_PASSWORD", "")
    name     = os.getenv("DB_NAME",     "tippspiel")
    return f"mysql+pymysql://{user}:{password}@{host}:{port}/{name}?charset=utf8mb4"


def init_db(app):
    app.config["SQLALCHEMY_DATABASE_URI"]        = _build_uri()
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["SQLALCHEMY_ENGINE_OPTIONS"]      = {
        "pool_recycle": 280,   # recycle connections before MySQL's wait_timeout
        "pool_pre_ping": True, # verify connection health before use
    }
    db.init_app(app)
