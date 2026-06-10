import os
import random
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash, session
from sqlalchemy.exc import IntegrityError

from database import db, init_db
from models import Spiel, Klasse, Tipp, AdminLogin, Spieler

ADMIN_PASSWORT   = os.environ.get("ADMIN_PASSWORT",   "adminTom123!")
MANAGER_PASSWORT = os.environ.get("MANAGER_PASSWORT", "Mananger-gms!")

app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET", "wm-tipp-geheim")

init_db(app)

with app.app_context():
    db.create_all()


# ── PIN helper ────────────────────────────────────────────────────────────────

def generiere_pin():
    """Generate a unique 6-digit PIN."""
    for _ in range(100):
        pin = str(random.randint(100000, 999999))
        if not Spieler.query.filter_by(pin=pin).first():
            return pin
    raise RuntimeError("Kein freier PIN gefunden.")


# ── Auth helpers ──────────────────────────────────────────────────────────────

def get_rolle():
    return session.get("rolle")


def require_admin():
    if get_rolle() == "admin":
        return True
    flash("Diese Seite ist nur für den Haupt-Admin zugänglich.", "error")
    return False


def require_staff():
    if get_rolle() in ("admin", "manager"):
        return True
    flash("Bitte melde dich an.", "error")
    return False


# ── Scoring ───────────────────────────────────────────────────────────────────

def punkte_fuer_tipp(tipp_heim, tipp_gast, tore_heim, tore_gast):
    if tore_heim is None or tore_gast is None:
        return 0
    if tipp_heim == tore_heim and tipp_gast == tore_gast:
        return 1
    return 0


def parse_anstoss(s):
    try:
        return datetime.fromisoformat(s)
    except (TypeError, ValueError):
        return None


# ── Tipp-Speicher-Hilfsfunktion ───────────────────────────────────────────────

def speichere_tipps(spiele, spieler_name, klasse):
    """Save submitted tips for `spieler_name`. Returns count saved."""
    jetzt = datetime.now().isoformat(timespec="seconds")
    gespeichert = 0
    for s in spiele:
        h  = request.form.get(f"tipp_heim_{s.id}")
        g_ = request.form.get(f"tipp_gast_{s.id}")
        if not h or not g_:
            continue
        try:
            th, tg = int(h), int(g_)
        except ValueError:
            continue
        if not (0 <= th <= 99 and 0 <= tg <= 99):
            continue
        tipp = Tipp.query.filter_by(spiel_id=s.id, spieler=spieler_name).first()
        if tipp:
            tipp.klasse    = klasse or None
            tipp.tipp_heim = th
            tipp.tipp_gast = tg
            tipp.abgegeben = jetzt
        else:
            tipp = Tipp(
                spiel_id=s.id, spieler=spieler_name,
                klasse=klasse or None,
                tipp_heim=th, tipp_gast=tg, abgegeben=jetzt,
            )
            db.session.add(tipp)
        gespeichert += 1
    return gespeichert


# ── Public routes ─────────────────────────────────────────────────────────────

@app.route("/", methods=["GET", "POST"])
def index():
    spiele  = Spiel.query.order_by(Spiel.id.asc()).all()
    klassen = Klasse.query.order_by(Klasse.name.asc()).all()

    spieler_name   = session.get("spieler_name")
    spieler_klasse = session.get("spieler_klasse")

    offene  = [s for s in spiele if s.tore_heim is None]
    beendet = [s for s in spiele if s.tore_heim is not None]

    # Welche offenen Spiele hat dieser Spieler noch NICHT getippt?
    if spieler_name:
        getippt_ids = {
            t.spiel_id for t in Tipp.query.filter_by(spieler=spieler_name).all()
        }
        ungetippt = [s for s in offene if s.id not in getippt_ids]
    else:
        ungetippt = offene

    if request.method == "POST":
        aktion = request.form.get("aktion", "neu")

        # ── Erstmalige Registrierung ──────────────────────────────────────────
        if aktion == "neu":
            vorname  = (request.form.get("vorname")  or "").strip()
            nachname = (request.form.get("nachname") or "").strip()
            klasse   = (request.form.get("klasse")   or "").strip()
            name     = " ".join(p for p in (vorname, nachname) if p)

            if not vorname or not nachname:
                flash("Bitte gib Vor- und Nachname ein.", "error")
                return redirect(url_for("index"))
            if klassen and not klasse:
                flash("Bitte wähle deine Klasse aus.", "error")
                return redirect(url_for("index"))

            # Name bereits vergeben?
            if Spieler.query.filter_by(name=name).first():
                flash("Dieser Name ist bereits vergeben – bitte melde dich mit deiner PIN an.", "error")
                return redirect(url_for("index"))

            pin = generiere_pin()
            db.session.add(Spieler(name=name, klasse=klasse or None, pin=pin))
            gespeichert = speichere_tipps(offene, name, klasse)
            db.session.commit()

            session["spieler_name"]   = name
            session["spieler_klasse"] = klasse
            session["spieler_pin"]    = pin
            return redirect(url_for("meine_pin"))

        # ── Nachtipp (eingeloggt, neue Spiele) ───────────────────────────────
        elif aktion == "nachtipp":
            if not spieler_name:
                flash("Bitte erst anmelden.", "error")
                return redirect(url_for("index"))
            gespeichert = speichere_tipps(ungetippt, spieler_name, spieler_klasse)
            db.session.commit()
            if gespeichert:
                flash(f"{gespeichert} Tipp(s) gespeichert!", "ok")
            else:
                flash("Keine Tipps gespeichert.", "error")
            return redirect(url_for("index"))

    return render_template(
        "index.html",
        spiele=spiele,
        klassen=klassen,
        offene=offene,
        ungetippt=ungetippt,
        beendet=beendet,
        spieler_name=spieler_name,
        spieler_klasse=spieler_klasse,
    )


@app.route("/pin-login", methods=["POST"])
def pin_login():
    pin = (request.form.get("pin") or "").strip()
    if not pin:
        flash("Bitte gib deine PIN ein.", "error")
        return redirect(url_for("index"))
    sp = Spieler.query.filter_by(pin=pin).first()
    if not sp:
        flash("Ungültige PIN. Bitte nochmal versuchen.", "error")
        return redirect(url_for("index"))
    session["spieler_name"]   = sp.name
    session["spieler_klasse"] = sp.klasse
    session["spieler_pin"]    = sp.pin
    flash(f"Willkommen zurück, {sp.name}!", "ok")
    return redirect(url_for("index"))


@app.route("/abmelden", methods=["POST"])
def abmelden():
    session.pop("spieler_name",   None)
    session.pop("spieler_klasse", None)
    session.pop("spieler_pin",    None)
    return redirect(url_for("index"))


@app.route("/meine-pin")
def meine_pin():
    name = session.get("spieler_name")
    pin  = session.get("spieler_pin")
    if not name or not pin:
        return redirect(url_for("index"))
    return render_template("meine_pin.html", spieler_name=name, pin=pin)


@app.route("/klassen-rangliste")
def klassen_rangliste():
    klassen = Klasse.query.order_by(Klasse.name.asc()).all()
    rows = (
        db.session.query(Tipp, Spiel)
        .join(Spiel, Tipp.spiel_id == Spiel.id)
        .filter(Tipp.klasse.isnot(None))
        .all()
    )

    kp, km = {}, {}
    for t, s in rows:
        k = t.klasse
        kp[k] = kp.get(k, 0) + punkte_fuer_tipp(
            t.tipp_heim, t.tipp_gast, s.tore_heim, s.tore_gast
        )
        km.setdefault(k, set()).add(t.spieler)

    alle = set(list(kp.keys()) + [kl.name for kl in klassen])
    ergebnis = sorted(
        [{"klasse": k, "punkte": kp.get(k, 0), "mitglieder": len(km.get(k, set()))} for k in alle],
        key=lambda x: (-x["punkte"], x["klasse"].lower()),
    )
    return render_template("klassen_rangliste.html", ergebnis=ergebnis)


# ── Rangliste (staff only) ────────────────────────────────────────────────────

@app.route("/rangliste")
def rangliste():
    if not require_staff():
        return redirect(url_for("admin"))
    rows = (
        db.session.query(Tipp, Spiel)
        .join(Spiel, Tipp.spiel_id == Spiel.id)
        .all()
    )

    stats = {}
    for t, s in rows:
        e = stats.setdefault(
            t.spieler,
            {"spieler": t.spieler, "klasse": t.klasse or "–",
             "punkte": 0, "tipps": 0, "treffer": 0},
        )
        e["tipps"] += 1
        if s.tore_heim is not None:
            p = punkte_fuer_tipp(t.tipp_heim, t.tipp_gast, s.tore_heim, s.tore_gast)
            e["punkte"] += p
            if p:
                e["treffer"] += 1

    data = sorted(
        stats.values(),
        key=lambda x: (-x["punkte"], -x["treffer"], x["spieler"].lower()),
    )
    return render_template("rangliste.html", rangliste=data)


# ── Admin ─────────────────────────────────────────────────────────────────────

@app.route("/admin", methods=["GET", "POST"])
def admin():
    if not get_rolle():
        if request.method == "POST" and "passwort" in request.form:
            name     = (request.form.get("admin_name") or "").strip()
            passwort = request.form.get("passwort", "")
            if not name:
                flash("Bitte gib deinen Namen ein.", "error")
                return render_template("admin_login.html")

            if passwort == ADMIN_PASSWORT:
                rolle = "admin"
            elif passwort == MANAGER_PASSWORT:
                rolle = "manager"
            else:
                flash("Falsches Passwort.", "error")
                return render_template("admin_login.html")

            eintrag = AdminLogin.query.filter_by(name=name).first()
            if eintrag and eintrag.gesperrt:
                flash(f'Das Konto "{name}" wurde gesperrt.', "error")
                return render_template("admin_login.html")

            jetzt = datetime.now().isoformat(timespec="seconds")
            if eintrag:
                eintrag.rolle         = rolle
                eintrag.letzter_login = jetzt
            else:
                db.session.add(AdminLogin(name=name, rolle=rolle, letzter_login=jetzt))
            db.session.commit()
            session["rolle"]      = rolle
            session["admin_name"] = name
            return redirect(url_for("admin"))
        return render_template("admin_login.html")

    rolle = get_rolle()

    if request.method == "POST":
        aktion = request.form.get("aktion")

        if aktion in ("spieler_loeschen", "konto_sperren", "konto_entsperren", "admin_entfernen"):
            if not require_admin():
                return redirect(url_for("admin"))

            if aktion == "spieler_loeschen":
                sp_name = (request.form.get("spieler") or "").strip()
                if sp_name:
                    Tipp.query.filter_by(spieler=sp_name).delete()
                    Spieler.query.filter_by(name=sp_name).delete()
                    db.session.commit()
                    flash(f'Konto "{sp_name}" gelöscht.', "ok")

            elif aktion == "konto_sperren":
                name = (request.form.get("login_name") or "").strip()
                if name == session.get("admin_name"):
                    flash("Du kannst dich nicht selbst sperren.", "error")
                elif name:
                    al = AdminLogin.query.filter_by(name=name).first()
                    if al:
                        al.gesperrt = 1
                        db.session.commit()
                    flash(f'"{name}" wurde gesperrt.', "ok")

            elif aktion == "konto_entsperren":
                name = (request.form.get("login_name") or "").strip()
                if name:
                    al = AdminLogin.query.filter_by(name=name).first()
                    if al:
                        al.gesperrt = 0
                        db.session.commit()
                    flash(f'"{name}" wurde entsperrt.', "ok")

            elif aktion == "admin_entfernen":
                name = (request.form.get("login_name") or "").strip()
                if name == session.get("admin_name"):
                    flash("Du kannst dich nicht selbst entfernen.", "error")
                elif name:
                    AdminLogin.query.filter_by(name=name).delete()
                    db.session.commit()
                    flash(f'"{name}" wurde entfernt.', "ok")

        elif aktion == "spiel_anlegen":
            th = (request.form.get("team_heim") or "").strip()
            tg = (request.form.get("team_gast") or "").strip()
            if not th or not tg:
                flash("Bitte beide Teams angeben.", "error")
            else:
                db.session.add(Spiel(
                    team_heim=th, team_gast=tg,
                    anstoss=datetime.now().isoformat(timespec="seconds"),
                ))
                db.session.commit()
                flash(f"Spiel angelegt: {th} – {tg}", "ok")

        elif aktion == "ergebnis_eintragen":
            try:
                sid = int(request.form.get("spiel_id", ""))
                th  = int(request.form.get("tore_heim", ""))
                tg  = int(request.form.get("tore_gast", ""))
            except ValueError:
                flash("Ungültige Eingabe.", "error")
            else:
                spiel = Spiel.query.get(sid)
                if spiel:
                    spiel.tore_heim = th
                    spiel.tore_gast = tg
                    db.session.commit()
                flash("Ergebnis gespeichert.", "ok")

        elif aktion == "spiel_loeschen":
            try:
                sid = int(request.form.get("spiel_id", ""))
            except ValueError:
                flash("Ungültige ID.", "error")
            else:
                Spiel.query.filter_by(id=sid).delete()
                db.session.commit()
                flash("Spiel gelöscht.", "ok")

        elif aktion == "klasse_anlegen":
            name = (request.form.get("klasse_name") or "").strip()
            if not name:
                flash("Bitte einen Klassennamen eingeben.", "error")
            else:
                try:
                    db.session.add(Klasse(name=name))
                    db.session.commit()
                    flash(f'Klasse "{name}" angelegt.', "ok")
                except IntegrityError:
                    db.session.rollback()
                    flash(f'Klasse "{name}" existiert bereits.', "error")

        elif aktion == "klasse_loeschen":
            try:
                kid = int(request.form.get("klasse_id", ""))
            except ValueError:
                flash("Ungültige Klassen-ID.", "error")
            else:
                Klasse.query.filter_by(id=kid).delete()
                db.session.commit()
                flash("Klasse gelöscht.", "ok")

        return redirect(url_for("admin"))

    # ── Render ──
    spiele  = Spiel.query.order_by(Spiel.id.asc()).all()
    klassen = Klasse.query.order_by(Klasse.name.asc()).all()

    spieler_liste = alle_tipps = admin_liste = None

    if rolle == "admin":
        # Spieler-Übersicht: Tipp-Anzahl, letzter Tipp, PIN
        from sqlalchemy import func
        spieler_rows = (
            db.session.query(
                Tipp.spieler, Tipp.klasse,
                func.count(Tipp.id).label("anzahl"),
                func.max(Tipp.abgegeben).label("letzter"),
                Spieler.pin,
            )
            .outerjoin(Spieler, Spieler.name == Tipp.spieler)
            .group_by(Tipp.spieler, Tipp.klasse, Spieler.pin)
            .order_by(func.max(Tipp.abgegeben).desc())
            .all()
        )
        punkte_rows = (
            db.session.query(Tipp, Spiel)
            .join(Spiel, Tipp.spiel_id == Spiel.id)
            .all()
        )
        pp = {}
        for t, s in punkte_rows:
            pp[t.spieler] = pp.get(t.spieler, 0) + punkte_fuer_tipp(
                t.tipp_heim, t.tipp_gast, s.tore_heim, s.tore_gast
            )
        spieler_liste = [
            {
                "spieler": row.spieler,
                "klasse":  row.klasse,
                "anzahl":  row.anzahl,
                "letzter": row.letzter,
                "pin":     row.pin,
                "punkte":  pp.get(row.spieler, 0),
            }
            for row in spieler_rows
        ]

        alle_tipps = (
            db.session.query(Tipp, Spiel)
            .join(Spiel, Tipp.spiel_id == Spiel.id)
            .order_by(Tipp.abgegeben.desc())
            .all()
        )
        # Flatten into dicts for the template (same keys as before)
        alle_tipps = [
            {
                "spieler":   t.spieler,
                "klasse":    t.klasse,
                "tipp_heim": t.tipp_heim,
                "tipp_gast": t.tipp_gast,
                "abgegeben": t.abgegeben,
                "team_heim": s.team_heim,
                "team_gast": s.team_gast,
                "tore_heim": s.tore_heim,
                "tore_gast": s.tore_gast,
            }
            for t, s in alle_tipps
        ]

        admin_liste = AdminLogin.query.order_by(AdminLogin.letzter_login.desc()).all()

    return render_template(
        "admin.html",
        spiele=spiele,
        klassen=klassen,
        spieler_liste=spieler_liste,
        alle_tipps=alle_tipps,
        admin_liste=admin_liste,
        rolle=rolle,
        admin_name=session.get("admin_name"),
    )


@app.route("/admin/logout", methods=["POST"])
def admin_logout():
    session.pop("rolle", None)
    session.pop("admin_name", None)
    flash("Abgemeldet.", "ok")
    return redirect(url_for("index"))


# ── Template filter ───────────────────────────────────────────────────────────

@app.template_filter("datum")
def datum_filter(s):
    dt = parse_anstoss(s) if isinstance(s, str) else s
    if dt is None:
        return s or "–"
    return dt.strftime("%a, %d.%m.%Y %H:%M")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
