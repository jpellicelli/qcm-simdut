# -*- coding: utf-8 -*-
import os, json, random, csv, datetime, shutil
from pathlib import Path
from flask import Flask, render_template, request, redirect, url_for, session, send_file, flash

APP_DIR = Path(__file__).resolve().parent

# 1. Définir le chemin de stockage selon l'environnement
# Render crée automatiquement une variable d'environnement RENDER=true
if os.environ.get("RENDER"):
    DATA_DIR = Path("/var/data")
else:
    DATA_DIR = APP_DIR

# 2. Assigner les fichiers au bon dossier
BANK_FILE = DATA_DIR / "banque_qcm_securite_simdut_env_A25.json"
BACKUP_DIR = DATA_DIR / "backups"
CSV_FILE  = DATA_DIR / "resultats_qcm.csv"

# 3. Initialiser le disque persistant
# Si le disque est vide (premier déploiement), on y copie la banque de questions initiale 
# qui se trouve dans les fichiers de votre code source (sur Github/Gitlab).
INITIAL_BANK = APP_DIR / "banque_qcm_securite_simdut_env_A25.json"
if not BANK_FILE.exists() and INITIAL_BANK.exists():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copy2(INITIAL_BANK, BANK_FILE)

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("FLASK_SECRET_KEY", "change-me-please")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "chimiegenerale")


def load_bank():
    if not BANK_FILE.exists():
        raise RuntimeError(f"Banque introuvable : {BANK_FILE.name}. Placez la banque JSON dans le dossier.")
    with open(BANK_FILE, "r", encoding="utf-8") as f:
        bank = json.load(f)
    if not isinstance(bank, list):
        raise RuntimeError("Banque invalide : format non-list.")
    for q in bank:
        for k in ("id","section","question","choices","answer"):
            if k not in q: raise RuntimeError(f"Banque invalide : champ {k} manquant.")
        if q["section"] not in ("A","B","C"): raise RuntimeError("Section invalide (A/B/C).")
        if set(q["choices"].keys()) != {"A","B","C","D"}: raise RuntimeError("Chaque question doit avoir A,B,C,D.")
        if q["answer"] not in ("A","B","C","D"): raise RuntimeError("Réponse doit être A/B/C/D.")
    return bank


def save_bank(bank):
    BACKUP_DIR.mkdir(exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    try: shutil.copy2(BANK_FILE, BACKUP_DIR / f"bank-{ts}.json")
    except FileNotFoundError: pass
    with open(BANK_FILE, "w", encoding="utf-8") as f:
        json.dump(bank, f, ensure_ascii=False, indent=2)


def pick_questions(bank):
    """
    Sélectionne 8 questions de la section A (sécurité),
    3 questions de la section B (SIMDUT/FDS),
    4 questions de la section C (déchets/environnement),
    pour un total de 15 questions.
    """
    sections = {"A": [], "B": [], "C": []}
    for q in bank:
        if q["section"] in sections:
            sections[q["section"]].append(q)

    required = {
        "A": 8,
        "B": 3,
        "C": 4
    }

    for s, n in required.items():
        if len(sections[s]) < n:
            raise RuntimeError(
                f"Section {s} contient {len(sections[s])} questions (< {n}). "
                "Ajoutez des questions dans la banque ou réduisez le nombre demandé."
            )

    chosen = []
    for s, n in required.items():
        chosen.extend(random.sample(sections[s], n))

    random.shuffle(chosen)
    return chosen


def require_admin():
    return session.get("is_admin") is True


# ---------- Élève ----------
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/start", methods=["POST"])
def start():
    nom = request.form.get("nom","").strip()
    matricule = request.form.get("matricule","").strip()
    if not nom or not matricule:
        flash("Veuillez entrer votre nom et votre matricule.")
        return redirect(url_for("index"))

    bank = load_bank()
    questions = pick_questions(bank)

    qpack = []
    for q in questions:

        # ------------------------------
        #  NE PAS MÉLANGER LES CHOIX
        # ------------------------------
        visible = [
            {"label": "A", "text": q["choices"]["A"]},
            {"label": "B", "text": q["choices"]["B"]},
            {"label": "C", "text": q["choices"]["C"]},
            {"label": "D", "text": q["choices"]["D"]},
        ]

        qpack.append({
            "id": q["id"], "section": q["section"], "question": q["question"],
            "visible": visible, "answer": q["answer"], "rationale": q.get("rationale","")
        })

    session["student"] = {"nom": nom, "matricule": matricule}
    session["quiz"] = qpack
    return render_template("quiz.html", student=session["student"], questions=qpack)


@app.route("/submit", methods=["POST"])
def submit():
    student = session.get("student")
    qpack   = session.get("quiz")
    if not student or not qpack:
        flash("Session expirée. Recommencez.")
        return redirect(url_for("index"))

    total, score, details = len(qpack), 0, []
    for q in qpack:
        ans = request.form.get(f"q_{q['id']}","").upper()
        correct = q["answer"]
        ok = (ans == correct)
        if ok: score += 1
        vis_text = {opt["label"]: opt["text"] for opt in q["visible"]}
        details.append({
            "id": q["id"], "section": q["section"], "question": q["question"],
            "given_vis": ans, "given_text": vis_text.get(ans,""),
            "correct_vis": correct, "correct_text": vis_text.get(correct,""),
            "is_correct": ok, "rationale": q.get("rationale","")
        })

    percent = round(100*score/total,1)

    new = not Path(CSV_FILE).exists()
    with open(CSV_FILE, "a", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        if new: w.writerow(["timestamp","nom","matricule","score","total","percent","details_json"])
        w.writerow([datetime.datetime.now().isoformat(timespec="seconds"),
                    student["nom"], student["matricule"],
                    score, total, percent,
                    json.dumps(details, ensure_ascii=False)])

    session.pop("quiz", None)
    return render_template("done.html", student=student, score=score, total=total, percent=percent, details=details)


# ---------- Admin ----------
@app.route("/admin", methods=["GET","POST"])
def admin_login():
    if request.method == "POST":
        if request.form.get("password","") == ADMIN_PASSWORD:
            session["is_admin"] = True
            return redirect(url_for("admin_dashboard"))
        flash("Mot de passe incorrect.")
    return render_template("admin_login.html")


@app.route("/admin/logout")
def admin_logout():
    session.pop("is_admin", None)
    flash("Déconnecté·e.")
    return redirect(url_for("admin_login"))


@app.route("/admin/dashboard")
def admin_dashboard():
    if not require_admin():
        flash("Authentification requise.")
        return redirect(url_for("admin_login"))

    rows = []
    if Path(CSV_FILE).exists():
        with open(CSV_FILE, encoding="utf-8") as f:
            rows = list(csv.DictReader(f))

    rows.sort(key=lambda x: x["timestamp"], reverse=True)
    total_sub = len(rows)
    avg = round(sum(float(r["percent"]) for r in rows) / total_sub, 1) if total_sub else 0.0

    return render_template("admin_dashboard.html", rows=rows, total_sub=total_sub, avg=avg)


@app.route("/admin/export")
def admin_export():
    if not require_admin():
        flash("Authentification requise.")
        return redirect(url_for("admin_login"))
    if not Path(CSV_FILE).exists():
        flash("Aucun résultat pour le moment.")
        return redirect(url_for("admin_dashboard"))
    return send_file(CSV_FILE, as_attachment=True, download_name="resultats_qcm.csv")


@app.route("/admin/bank")
def admin_bank():
    if not require_admin():
        flash("Authentification requise.")
        return redirect(url_for("admin_login"))

    bank = load_bank()
    sect = request.args.get("section")
    if sect in ("A","B","C"):
        bank = [q for q in bank if q["section"] == sect]

    return render_template("admin_bank.html", bank=sorted(bank, key=lambda x: (x["section"], x["id"])) )


@app.route("/admin/bank/new", methods=["GET","POST"])
def admin_bank_new():
    if not require_admin():
        flash("Authentification requise.")
        return redirect(url_for("admin_login"))

    if request.method == "POST":
        bank = load_bank()
        try:
            qid = int(request.form["id"])
            section = request.form["section"].strip()
            question = request.form["question"].strip()
            choices = {
                "A": request.form["A"].strip(),
                "B": request.form["B"].strip(),
                "C": request.form["C"].strip(),
                "D": request.form["D"].strip(),
            }
            answer = request.form["answer"].strip().upper()
            rationale = request.form.get("rationale","").strip()

            if any(q["id"] == qid for q in bank):
                flash("ID déjà existant.")
                return redirect(url_for("admin_bank_new"))

            if section not in ("A","B","C"): raise ValueError("Section invalide.")
            if answer not in ("A","B","C","D"): raise ValueError("Réponse invalide.")

            bank.append({"id": qid, "section": section, "question": question,
                         "choices": choices, "answer": answer, "rationale": rationale})

            save_bank(bank)
            flash("Question ajoutée.")
            return redirect(url_for("admin_bank"))

        except Exception as e:
            flash(f"Erreur: {e}")

    return render_template("admin_bank_edit.html", mode="new", q=None)


@app.route("/admin/bank/edit/<int:qid>", methods=["GET","POST"])
def admin_bank_edit(qid):
    if not require_admin():
        flash("Authentification requise.")
        return redirect(url_for("admin_login"))

    bank = load_bank()
    q = next((x for x in bank if x["id"] == qid), None)

    if not q:
        flash("Question introuvable.")
        return redirect(url_for("admin_bank"))

    if request.method == "POST":
        try:
            q["section"]  = request.form["section"].strip()
            q["question"] = request.form["question"].strip()
            q["choices"]["A"] = request.form["A"].strip()
            q["choices"]["B"] = request.form["B"].strip()
            q["choices"]["C"] = request.form["C"].strip()
            q["choices"]["D"] = request.form["D"].strip()
            q["answer"] = request.form["answer"].strip().upper()
            q["rationale"] = request.form.get("rationale","").strip()

            if q["section"] not in ("A","B","C"): raise ValueError("Section invalide.")
            if q["answer"] not in ("A","B","C","D"): raise ValueError("Réponse invalide.")

            save_bank(bank)
            flash("Question modifiée.")
            return redirect(url_for("admin_bank"))

        except Exception as e:
            flash(f"Erreur: {e}")

    return render_template("admin_bank_edit.html", mode="edit", q=q)


@app.route("/admin/bank/delete/<int:qid>", methods=["POST"])
def admin_bank_delete(qid):
    if not require_admin():
        flash("Authentification requise.")
        return redirect(url_for("admin_login"))

    bank = load_bank()
    bank2 = [q for q in bank if q["id"] != qid]

    if len(bank2) == len(bank):
        flash("Question introuvable.")
    else:
        save_bank(bank2)
        flash("Question supprimée.")

    return redirect(url_for("admin_bank"))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT",5000)), debug=False)
