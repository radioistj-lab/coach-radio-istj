import io
import html
import base64
import hashlib
import hmac
import secrets
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import streamlit as st
from openai import OpenAI

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    KeepTogether,
)


# =========================================================
# CONFIGURATION
# =========================================================

st.set_page_config(
    page_title="Coach d'écriture Radio ISTJ",
    page_icon="🎙️",
    layout="centered"
)

MODEL = "gpt-5.6-luna"


# =========================================================
# ACCÈS PROTÉGÉ — PROFESSEUR + CODES ÉLÈVES TEMPORAIRES
# =========================================================

PARIS = ZoneInfo("Europe/Paris")


def _base36_encode(nombre):
    caracteres = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    if nombre == 0:
        return "0"

    resultat = ""
    while nombre:
        nombre, reste = divmod(nombre, 36)
        resultat = caracteres[reste] + resultat
    return resultat


def _base36_decode(texte):
    return int(texte, 36)


def _normaliser_code_temporaire(code):
    return "".join(
        caractere for caractere in str(code).upper()
        if caractere.isalnum()
    )


def _formater_code_temporaire(code):
    brut = _normaliser_code_temporaire(code)
    return "-".join(
        brut[i:i + 4]
        for i in range(0, len(brut), 4)
    )


def _secret_token():
    try:
        valeur = str(st.secrets["TOKEN_SECRET"]).strip()
    except Exception:
        valeur = ""

    if not valeur:
        raise RuntimeError(
            "TOKEN_SECRET n'est pas configuré dans les Secrets Streamlit."
        )

    return valeur.encode("utf-8")


def generer_code_temporaire(duree_heures):
    """Crée un code signé, vérifiable sans base de données."""
    expiration = int(time.time()) + int(duree_heures * 3600)

    expiration_minutes = expiration // 60
    bloc_expiration = _base36_encode(expiration_minutes).rjust(6, "0")[-6:]

    nonce = base64.b32encode(secrets.token_bytes(3)).decode("ascii").rstrip("=")
    nonce = nonce[:5]

    message = f"{bloc_expiration}{nonce}".encode("ascii")
    signature = hmac.new(
        _secret_token(),
        message,
        hashlib.sha256
    ).digest()[:5]

    bloc_signature = base64.b32encode(signature).decode("ascii").rstrip("=")
    code = f"{bloc_expiration}{nonce}{bloc_signature}"

    expiration_reelle = expiration_minutes * 60 + 59
    return _formater_code_temporaire(code), expiration_reelle


def verifier_code_temporaire(code):
    """Retourne (valide, expiration, message)."""
    brut = _normaliser_code_temporaire(code)

    if len(brut) != 19:
        return False, 0, "Code élèves invalide."

    bloc_expiration = brut[:6]
    nonce = brut[6:11]
    signature_fournie = brut[11:]

    try:
        expiration_minutes = _base36_decode(bloc_expiration)
    except ValueError:
        return False, 0, "Code élèves invalide."

    message = f"{bloc_expiration}{nonce}".encode("ascii")
    signature = hmac.new(
        _secret_token(),
        message,
        hashlib.sha256
    ).digest()[:5]
    signature_attendue = base64.b32encode(signature).decode("ascii").rstrip("=")

    if not hmac.compare_digest(signature_fournie, signature_attendue):
        return False, 0, "Code élèves invalide."

    expiration = expiration_minutes * 60 + 59

    if time.time() > expiration:
        return False, expiration, "Ce code élèves a expiré."

    return True, expiration, ""


def heure_locale(timestamp):
    return datetime.fromtimestamp(timestamp, tz=PARIS).strftime("%H:%M")


def afficher_carte_role(emoji, titre, sous_titre, couleur="#153A63"):
    st.markdown(
        f"""
        <div style="
            border: 1px solid #dfe5ec;
            border-radius: 18px;
            padding: 28px 16px 22px 16px;
            text-align: center;
            background: #ffffff;
            min-height: 340px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.04);
            display: flex;
            flex-direction: column;
            justify-content: center;
        ">
            <div style="font-size: 7rem; line-height: 1; margin-bottom: 24px;">
                {emoji}
            </div>
            <div style="font-size: 1.55rem; font-weight: 700; color: {couleur}; margin-top: 4px;">
                {titre}
            </div>
            <div style="font-size: 0.95rem; color: #555555; margin-top: 12px;">
                {sous_titre}
            </div>
        </div>
        """,
        unsafe_allow_html=True
    )


def afficher_pied_page_application():
    st.markdown(
        """
        <div style="
            margin-top: 3rem;
            padding-top: 1rem;
            border-top: 1px solid #e6e6e6;
            text-align: center;
            color: #777777;
            font-size: 0.82rem;
            line-height: 1.5;
        ">
            <strong>Coach d’écriture Radio ISTJ</strong><br>
            © 2026 C. Declerck — Tous droits réservés
        </div>
        """,
        unsafe_allow_html=True
    )


if "acces_autorise" not in st.session_state:
    st.session_state.acces_autorise = False

if "acces_expire_at" not in st.session_state:
    st.session_state.acces_expire_at = 0

if "professeur_autorise" not in st.session_state:
    st.session_state.professeur_autorise = False

if "code_temporaire_genere" not in st.session_state:
    st.session_state.code_temporaire_genere = ""

if "code_temporaire_expiration" not in st.session_state:
    st.session_state.code_temporaire_expiration = 0

if "mode_acces" not in st.session_state:
    st.session_state.mode_acces = ""

if "message_expiration" not in st.session_state:
    st.session_state.message_expiration = ""


# Un élève déjà connecté est automatiquement déconnecté à l'expiration.
if (
    st.session_state.acces_autorise
    and st.session_state.acces_expire_at
    and time.time() > st.session_state.acces_expire_at
):
    st.session_state.acces_autorise = False
    st.session_state.acces_expire_at = 0
    st.session_state.message_expiration = (
        "Ton accès a expiré. Demande un nouveau code à ton professeur."
    )


if not st.session_state.acces_autorise:

    st.title("🎙️ Coach d'écriture Radio ISTJ")
    st.caption("Choisis ton espace pour continuer.")

    if st.session_state.message_expiration:
        st.warning(st.session_state.message_expiration)
        st.session_state.message_expiration = ""

    # -----------------------------------------------------
    # CHOIX DU PROFIL
    # -----------------------------------------------------
    if not st.session_state.mode_acces:

        col_eleve, col_prof = st.columns(2, gap="large")

        with col_eleve:
            afficher_carte_role(
                "🎙️",
                "Élève",
                "J'entre avec le code de ma séance.",
                "#153A63"
            )
            if st.button(
                "Entrer comme élève",
                key="choisir_eleve",
                use_container_width=True
            ):
                st.session_state.mode_acces = "eleve"
                st.rerun()

        with col_prof:
            afficher_carte_role(
                "👩‍🏫",
                "Professeur",
                "Je crée un accès pour mon groupe.",
                "#4E8B45"
            )
            if st.button(
                "Entrer comme professeur",
                key="choisir_professeur",
                use_container_width=True
            ):
                st.session_state.mode_acces = "professeur"
                st.rerun()

    # -----------------------------------------------------
    # ESPACE ÉLÈVE
    # -----------------------------------------------------
    elif st.session_state.mode_acces == "eleve":

        col_retour, _ = st.columns([1, 3])
        with col_retour:
            if st.button("← Changer de profil"):
                st.session_state.mode_acces = ""
                st.rerun()

        st.subheader("🎙️ Accès élève")
        st.write(
            "Entre le code temporaire donné par ton professeur "
            "pour utiliser le Coach Radio ISTJ."
        )

        code_saisi = st.text_input(
            "Code élèves",
            placeholder="XXXX-XXXX-XXXX-XXXX-XXX"
        )

        if st.button("Entrer", use_container_width=True):
            try:
                valide, expiration, message = verifier_code_temporaire(code_saisi)
            except RuntimeError as e:
                st.error(str(e))
                afficher_pied_page_application()
                st.stop()

            if valide:
                st.session_state.acces_autorise = True
                st.session_state.acces_expire_at = expiration
                st.rerun()
            else:
                st.error(message)

    # -----------------------------------------------------
    # ESPACE PROFESSEUR
    # -----------------------------------------------------
    else:

        if not st.session_state.professeur_autorise:

            col_retour, _ = st.columns([1, 3])
            with col_retour:
                if st.button("← Changer de profil"):
                    st.session_state.mode_acces = ""
                    st.rerun()

            st.subheader("👩‍🏫 Accès professeur")
            st.caption(
                "Le code professeur est permanent et ne doit pas être communiqué "
                "aux élèves."
            )

            code_professeur = st.text_input(
                "Code professeur",
                type="password"
            )

            if st.button("Ouvrir l'espace professeur", use_container_width=True):
                try:
                    code_attendu = str(st.secrets["TEACHER_CODE"]).strip()
                except Exception:
                    code_attendu = ""

                if not code_attendu:
                    st.error(
                        "TEACHER_CODE n'est pas configuré dans les Secrets Streamlit."
                    )
                elif hmac.compare_digest(code_professeur.strip(), code_attendu):
                    st.session_state.professeur_autorise = True
                    st.rerun()
                else:
                    st.error("Code professeur incorrect.")

        else:

            st.subheader("👩‍🏫 Espace professeur")
            st.write(
                "Génère un code à communiquer aux élèves au début de la séance."
            )

            duree = st.radio(
                "Durée de validité",
                ["1 heure", "2 heures"],
                horizontal=True
            )

            if st.button("🔑 Générer un nouveau code élèves", use_container_width=True):
                try:
                    code, expiration = generer_code_temporaire(
                        1 if duree == "1 heure" else 2
                    )
                except RuntimeError as e:
                    st.error(str(e))
                else:
                    st.session_state.code_temporaire_genere = code
                    st.session_state.code_temporaire_expiration = expiration

            if st.session_state.code_temporaire_genere:
                st.success("Code élèves prêt")
                st.code(st.session_state.code_temporaire_genere, language=None)
                st.write(
                    "**Valable jusqu'à "
                    f"{heure_locale(st.session_state.code_temporaire_expiration)}**"
                )
                st.caption(
                    "Tu peux écrire ce code au tableau. Il deviendra "
                    "automatiquement inutilisable après l'heure indiquée."
                )

            st.divider()

            if st.button("Fermer l'espace professeur"):
                st.session_state.professeur_autorise = False
                st.session_state.code_temporaire_genere = ""
                st.session_state.code_temporaire_expiration = 0
                st.session_state.mode_acces = ""
                st.rerun()

    afficher_pied_page_application()
    st.stop()


# =========================================================
# FONCTIONS GÉNÉRALES
# =========================================================

def initialiser(cle, valeur=""):
    if cle not in st.session_state:
        st.session_state[cle] = valeur


def appel_ia(instructions, contenu):
    client = OpenAI(
        api_key=st.secrets["OPENAI_API_KEY"]
    )

    response = client.responses.create(
        model=MODEL,
        instructions=instructions,
        input=contenu
    )

    return response.output_text


def est_valide(feedback, mot):
    return feedback.strip().startswith(mot)


def contexte_documentaire():

    if st.session_state.parcours == "guide":
        return st.session_state.source

    return f"""
THÈME :
{st.session_state.libre_theme}

SUJET :
{st.session_state.libre_sujet}

ANGLE :
{st.session_state.libre_angle}

RECHERCHES / DOCUMENTS / NOTES :
{st.session_state.libre_recherches}

INFORMATIONS RETENUES PAR L'ÉLÈVE :
{st.session_state.libre_infos}
"""


def references_affichees():

    if st.session_state.parcours == "guide":

        return (
            f"Auteur : {st.session_state.ref_auteur.strip()}\n"
            f"Titre : {st.session_state.ref_titre.strip()}\n"
            f"Média : {st.session_state.ref_media.strip()}\n"
            f"Date : {st.session_state.ref_date.strip()}"
        )

    return st.session_state.libre_references.strip()


def assembler_chronique():
    """
    Assemble uniquement le texte destiné à être lu à l'antenne.

    Les références / sources ne sont PAS ajoutées à la chronique orale.
    Elles restent stockées séparément et apparaissent dans le PDF.
    """

    parties = [
        st.session_state.introduction.strip(),
        st.session_state.developpement.strip(),
        st.session_state.conclusion.strip(),
    ]

    return "\n\n".join(
        partie for partie in parties if partie
    )


def invalider_apres(partie):

    ordre = {
        "comprehension": 1,
        "plan": 2,
        "introduction": 3,
        "developpement": 4,
        "conclusion": 5,
        "references": 6,
    }

    niveau = ordre[partie]

    if niveau <= 1:
        st.session_state.feedback_comprehension = ""

    if niveau <= 2:
        st.session_state.feedback_plan = ""

    if niveau <= 3:
        st.session_state.feedback_introduction = ""

    if niveau <= 4:
        st.session_state.feedback_developpement = ""

    if niveau <= 5:
        st.session_state.feedback_conclusion = ""

    if niveau <= 6:
        st.session_state.feedback_references = ""

    st.session_state.chronique = ""
    st.session_state.feedback_final = ""


# =========================================================
# SIDEBAR PÉDAGOGIQUE DU PARCOURS LIBRE
# =========================================================

def afficher_sidebar_libre():

    if st.session_state.get("parcours") != "libre":
        return

    etape = st.session_state.get("etape", "")

    with st.sidebar:

        st.header("📻 Mémo écriture radio")

        if etape in [
            "libre_cadrage",
            "libre_angle_verif"
        ]:

            st.subheader("Thème → Sujet → Angle")

            st.markdown(
                """
**Thème**

Le domaine général dont tu veux parler.

**Sujet**

Une partie plus précise de ce thème.

**Angle**

L'aspect précis du sujet que tu choisis de traiter.

👉 **L'angle donne la direction de tes recherches et de ta chronique.**

Tu ne dois pas tout raconter.
"""
            )

            st.divider()

            st.caption("Exemple")

            st.markdown(
                """
**Thème :**  
La rentrée scolaire

**Sujet :**  
La rentrée 2026 dans notre collège

**Angle :**  
Les principaux changements de la rentrée 2026 dans notre collège
"""
            )

            st.info(
                "Un même sujet peut avoir plusieurs angles."
            )

        elif etape in [
            "libre_recherches",
            "libre_recherches_verif",
            "libre_5w"
        ]:

            st.subheader("Garde ton angle en tête")

            if st.session_state.libre_angle:

                st.write(
                    f"**Ton angle :**  \n"
                    f"{st.session_state.libre_angle}"
                )

            st.markdown(
                """
Pendant tes recherches, demande-toi :

**Est-ce que cette information sert vraiment mon angle ?**
"""
            )

            st.divider()

            st.subheader("Les 5 W")

            st.markdown(
                """
**WHAT ?**  
De quoi parle-t-on ?

**WHO ?**  
Qui est concerné ?

**WHERE ?**  
Où cela se passe-t-il ?

**WHEN ?**  
Quand ?

**WHY / HOW ?**  
Pourquoi ? Comment ?  
Que faut-il faire comprendre ?
"""
            )

            st.caption(
                "Toutes ces questions ne sont pas forcément utiles "
                "pour chaque chronique."
            )

        elif etape in [
            "plan",
            "plan_enregistre",
            "introduction",
            "controle_introduction",
            "developpement",
            "controle_developpement",
            "conclusion",
            "controle_conclusion"
        ]:

            st.subheader("Les 3 C")

            st.markdown(
                """
### Court
Privilégie les phrases courtes.

### Clair
L'auditeur doit comprendre à la première écoute.

### Concis
Va à l'essentiel et utilise des mots précis.
"""
            )

            st.divider()

            st.markdown(
                """
**Une phrase = une idée**

🎙️ Écris pour être entendu, pas seulement pour être lu.
"""
            )

            if st.session_state.libre_angle:

                st.divider()

                st.subheader("Ton angle")

                st.write(
                    st.session_state.libre_angle
                )

                st.caption(
                    "Ton texte doit rester centré sur cet angle."
                )

            st.divider()

            st.subheader("Pense radio")

            st.markdown(
                """
- Une bonne **accroche** peut donner envie d'écouter.
- Tu peux créer des **images mentales**.
- Tu peux imaginer des **sons ou un habillage sonore**.

Ces éléments sont des possibilités, pas des obligations.
"""
            )

        elif etape in [
            "references",
            "controle_references"
        ]:

            st.subheader("Tes sources")

            st.markdown(
                """
Une information doit pouvoir être reliée à une source.

Une source peut être par exemple :

- une observation directe ;
- une information donnée dans le collège ;
- un document ou un site ;
- un témoignage ;
- une interview déjà réalisée.

Pour un article ou un site, indique si possible :

- auteur ou organisme ;
- titre ;
- média ou site ;
- date ;
- lien si tu l'as.
"""
            )

            st.warning(
                "Une interview seulement prévue n'est pas encore "
                "une source utilisée."
            )

            if st.session_state.libre_angle:

                st.divider()

                st.caption("Angle de ta chronique")

                st.write(
                    st.session_state.libre_angle
                )

        elif etape in [
            "chronique_assemblee",
            "controle_final"
        ]:

            st.subheader("Dernière vérification")

            st.markdown(
                """
Ta chronique doit être :

**✓ fidèle à tes recherches**

**✓ centrée sur ton angle**

**✓ claire à l'écoute**

**✓ écrite avec tes propres phrases**

**✓ courte et concise**

**✓ sans phrases adressées au Coach**
"""
            )

            if st.session_state.libre_angle:

                st.divider()

                st.caption("Ton angle")

                st.write(
                    st.session_state.libre_angle
                )


# =========================================================
# PDF
# =========================================================

def texte_pdf(texte):

    texte = str(texte)

    remplacements = {
        "\u202f": " ",
        "\u00a0": " ",
        "\u2011": "-",
        "\u2013": "-",
        "\u2014": "-",
        "\u2026": "...",
    }

    for ancien, nouveau in remplacements.items():
        texte = texte.replace(ancien, nouveau)

    texte = html.escape(texte)

    return texte.replace("\n", "<br/>")


def pied_de_page(canvas, doc):

    canvas.saveState()

    largeur, hauteur = A4

    canvas.setStrokeColor(colors.HexColor("#CCCCCC"))
    canvas.setLineWidth(0.5)

    canvas.line(
        2 * cm,
        1.45 * cm,
        largeur - 2 * cm,
        1.45 * cm
    )

    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.HexColor("#666666"))

    canvas.drawString(
        2 * cm,
        1 * cm,
        "Radio ISTJ - Coach d'écriture"
    )

    canvas.drawRightString(
        largeur - 2 * cm,
        1 * cm,
        f"Page {doc.page}"
    )

    canvas.restoreState()


def generer_pdf():

    buffer = io.BytesIO()

    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=2 * cm,
        leftMargin=2 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
        title="Chronique Radio ISTJ",
        author="Radio ISTJ"
    )

    styles = getSampleStyleSheet()

    style_radio = ParagraphStyle(
        "Radio",
        parent=styles["Title"],
        fontName="Helvetica-Bold",
        fontSize=22,
        leading=26,
        alignment=TA_CENTER,
        textColor=colors.HexColor("#153A63"),
        spaceAfter=4
    )

    style_sous_titre = ParagraphStyle(
        "SousTitre",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=10.5,
        leading=14,
        alignment=TA_CENTER,
        textColor=colors.HexColor("#555555"),
        spaceAfter=16
    )

    style_section = ParagraphStyle(
        "Section",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=13,
        leading=16,
        textColor=colors.HexColor("#153A63"),
        spaceBefore=10,
        spaceAfter=8
    )

    style_texte = ParagraphStyle(
        "TexteChronique",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=11,
        leading=16,
        spaceAfter=12
    )

    style_reference = ParagraphStyle(
        "References",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=9.5,
        leading=13,
        textColor=colors.HexColor("#444444"),
        spaceAfter=4
    )

    elements = []

    elements.append(
        Paragraph(
            "RADIO ISTJ",
            style_radio
        )
    )

    parcours_pdf = (
        "Parcours guidé"
        if st.session_state.parcours == "guide"
        else "Parcours libre"
    )

    elements.append(
        Paragraph(
            f"Chronique élève - {parcours_pdf} - version validée",
            style_sous_titre
        )
    )

    infos = (
        f"<b>Niveau :</b> {texte_pdf(st.session_state.niveau)}"
        f"&nbsp;&nbsp;&nbsp;&nbsp;"
        f"<b>Format :</b> {texte_pdf(st.session_state.nombre_voix)}"
    )

    elements.append(
        Paragraph(
            infos,
            style_sous_titre
        )
    )

    if st.session_state.parcours == "libre":

        elements.append(
            Paragraph(
                f"<b>Sujet :</b> "
                f"{texte_pdf(st.session_state.libre_sujet)}",
                style_sous_titre
            )
        )

    elements.append(Spacer(1, 0.2 * cm))

    elements.append(
        Paragraph(
            "Chronique",
            style_section
        )
    )

    elements.append(
        Paragraph(
            texte_pdf(st.session_state.introduction),
            style_texte
        )
    )

    elements.append(
        Paragraph(
            texte_pdf(st.session_state.developpement),
            style_texte
        )
    )

    elements.append(
        Paragraph(
            texte_pdf(st.session_state.conclusion),
            style_texte
        )
    )

    elements.append(Spacer(1, 0.35 * cm))

    bloc_references = [
        Paragraph(
            "Sources utilisées"
            if st.session_state.parcours == "libre"
            else "Références",
            style_section
        ),
        Paragraph(
            texte_pdf(references_affichees()),
            style_reference
        )
    ]

    elements.append(
        KeepTogether(bloc_references)
    )

    document.build(
        elements,
        onFirstPage=pied_de_page,
        onLaterPages=pied_de_page
    )

    pdf = buffer.getvalue()

    buffer.close()

    return pdf


# =========================================================
# VARIABLES DE SESSION
# =========================================================

initialiser("etape", "accueil")

initialiser("parcours", "")
initialiser("niveau", "6e-5e")
initialiser("nombre_voix", "1 voix")

# Parcours guidé
initialiser("source")
initialiser("sujet")
initialiser("idees")
initialiser("vocabulaire")
initialiser("feedback_comprehension")

# Parcours libre
initialiser("libre_theme")
initialiser("libre_sujet")
initialiser("libre_angle")
initialiser("feedback_angle")

initialiser("libre_recherches")
initialiser("libre_infos")
initialiser("feedback_recherches")

initialiser("libre_what")
initialiser("libre_who")
initialiser("libre_where")
initialiser("libre_when")
initialiser("libre_whyhow")

# Plan commun
initialiser("plan_introduction")
initialiser("plan_developpement")
initialiser("plan_conclusion")
initialiser("plan_repartition")
initialiser("feedback_plan")

# Rédaction commune
initialiser("introduction")
initialiser("feedback_introduction")

initialiser("developpement")
initialiser("feedback_developpement")

initialiser("conclusion")
initialiser("feedback_conclusion")

# Références guidées
initialiser("ref_auteur")
initialiser("ref_titre")
initialiser("ref_media")
initialiser("ref_date")

# Sources libres
initialiser("libre_references")

initialiser("feedback_references")

# Final
initialiser("chronique")
initialiser("feedback_final")


# =========================================================
# RÈGLES COMMUNES DE RÉDACTION
# =========================================================

REGLES_REDACTION = """
Tu es le Coach d'écriture pédagogique de Radio ISTJ.

Tu accompagnes un élève de collège qui écrit lui-même
une chronique destinée à être entendue à la radio.

RÈGLE ABSOLUE :
L'élève est l'auteur.

Tu ne dois JAMAIS :
- écrire une phrase de chronique à sa place ;
- proposer une reformulation prête à copier ;
- écrire une introduction modèle ;
- écrire une conclusion modèle ;
- donner un début ou une fin de phrase ;
- rédiger une transition ;
- rédiger une réplique à sa place ;
- fournir une version améliorée du texte.

Tu peux :
- analyser ;
- questionner ;
- signaler UNE difficulté ;
- rappeler une règle d'écriture radio ;
- donner quelques mots-clés si nécessaire.

=========================================================
DISTINGUER CHRONIQUE ET DIALOGUE AVEC LE COACH
=========================================================

Le texte de la chronique doit contenir uniquement
ce qui est destiné à être dit à l'antenne.

Une phrase ajoutée uniquement pour répondre
à une question du Coach ne fait PAS partie de la chronique.

Exemples de phrases de dialogue avec le Coach :

- « Oui, je confirme que... »
- « Non, je voulais dire que... »
- « Comme je l'ai expliqué... »
- « Je confirme bien que... »
- « Oui c'est exact... »

Si une telle phrase apparaît dans le texte destiné à l'antenne,
elle doit être retirée ou transformée PAR L'ÉLÈVE
en véritable phrase de chronique si l'information est utile.

Tu ne dois jamais considérer une réponse métadiscursive
adressée au Coach comme une phrase radiophonique normale.

=========================================================
RÈGLES RADIO
=========================================================

COURT :
- privilégier les phrases courtes ;
- une phrase porte de préférence une idée.

CLAIR :
- le texte doit être compris à la première écoute ;
- les liens logiques doivent rester compréhensibles.

CONCIS :
- utiliser des mots précis ;
- éviter les détours inutiles.

L'accroche doit donner envie d'écouter.

L'écriture peut aussi être descriptive,
créer des images mentales et penser aux sons,
mais ces éléments ne sont jamais obligatoires
dans toutes les chroniques.

NE TRANSFORME PAS ces conseils en grille rigide.

Une chronique simple mais claire peut être excellente.

=========================================================
RÉPÉTITIONS
=========================================================

Une même idée peut naturellement être :
- annoncée brièvement dans l'introduction ;
- développée ensuite ;
- rappelée brièvement dans la conclusion.

Ce n'est PAS automatiquement une mauvaise répétition.

En revanche, une répétition devient gênante
si deux passages successifs ou proches disent pratiquement
la même chose avec presque le même niveau de détail
et n'apportent rien de nouveau.

Ne cherche pas à supprimer toute répétition.

Signale uniquement les répétitions réellement lourdes
qui rendent la chronique inutilement longue
ou donnent l'impression que le même passage est dit deux fois.

=========================================================
FIDÉLITÉ
=========================================================

Tu travailles uniquement à partir des documents et recherches
fournis par l'élève dans l'application.

N'ajoute aucune connaissance extérieure.

SÉLECTIONNER N'EST PAS DÉFORMER.

Une chronique n'est jamais obligée de reprendre
toutes les informations disponibles.

=========================================================
NIVEAUX
=========================================================

NIVEAU 6e-5e :
- phrases simples acceptées ;
- vocabulaire simple accepté ;
- organisation simple acceptée ;
- quelques idées correctement traitées peuvent suffire.

NIVEAU 4e-3e :
attends davantage :
- de précision ;
- de liens ;
- d'explications ;
- de progression logique.

Mais jamais d'exhaustivité.

=========================================================
SI UNE CORRECTION EST NÉCESSAIRE
=========================================================

- commence par ce qui fonctionne ;
- choisis UNE seule difficulté prioritaire ;
- ne fournis pas la correction ;
- pose UNE question ciblée ;
- laisse l'élève reformuler lui-même.

Ne cherche pas la perfection.
Cherche un seuil suffisant pour une chronique radio de collège.
"""


# =========================================================
# TITRE + SIDEBAR
# =========================================================

st.title("🎙️ Coach d'écriture Radio ISTJ")

afficher_sidebar_libre()


# =========================================================
# ACCUEIL
# =========================================================

if st.session_state.etape == "accueil":

    st.write(
        "Prépare ta chronique radio étape par étape."
    )

    st.divider()

    niveau = st.radio(
        "Quel est ton niveau ?",
        ["6e-5e", "4e-3e"],
        horizontal=True
    )

    nombre_voix = st.radio(
        "Combien de voix pour la chronique ?",
        ["1 voix", "2 voix", "3 voix"],
        horizontal=True
    )

    st.divider()

    st.subheader("Comment veux-tu préparer ta chronique ?")

    parcours = st.radio(
        "Choisis ton parcours :",
        [
            "📄 Parcours guidé — Je pars d'une source",
            "💡 Parcours libre — Je pars d'une idée"
        ]
    )

    if parcours.startswith("📄"):

        st.info(
            "Tu as déjà un article ou un document. "
            "Le Coach t'aide à le comprendre, construire ton plan "
            "et rédiger ta chronique."
        )

        source = st.text_area(
            "Colle ici l'article ou la source :",
            height=300
        )

        if st.button("Commencer le parcours guidé"):

            if not source.strip():

                st.warning(
                    "Tu dois d'abord fournir une source."
                )

            else:

                st.session_state.parcours = "guide"
                st.session_state.niveau = niveau
                st.session_state.nombre_voix = nombre_voix
                st.session_state.source = source
                st.session_state.etape = "comprehension"

                st.rerun()

    else:

        st.info(
            "Tu pars d'une idée ou d'un thème. "
            "Le Coach t'aide à préciser ton sujet, choisir ton angle, "
            "organiser tes recherches et écrire pour la radio."
        )

        if st.button("Commencer le parcours libre"):

            st.session_state.parcours = "libre"
            st.session_state.niveau = niveau
            st.session_state.nombre_voix = nombre_voix
            st.session_state.etape = "libre_cadrage"

            st.rerun()


# =========================================================
# PARCOURS GUIDÉ — COMPRÉHENSION
# =========================================================

elif st.session_state.etape == "comprehension":

    st.subheader("Étape 1 — Comprendre la source")

    st.write(
        f"**Niveau :** {st.session_state.niveau}  \n"
        f"**Format :** {st.session_state.nombre_voix}"
    )

    sujet = st.text_area(
        "Quel est le sujet principal ?",
        value=st.session_state.sujet
    )

    idees = st.text_area(
        "Quelles sont les 2 ou 3 idées importantes ?",
        value=st.session_state.idees,
        height=160
    )

    vocabulaire = st.text_area(
        "Y a-t-il un mot ou un passage que tu ne comprends pas ? "
        "Si tout est clair, écris : Aucun.",
        value=st.session_state.vocabulaire
    )

    if st.button("Continuer"):

        if not sujet.strip() or not idees.strip() or not vocabulaire.strip():

            st.warning(
                "Complète les trois parties avant de continuer."
            )

        else:

            st.session_state.sujet = sujet
            st.session_state.idees = idees
            st.session_state.vocabulaire = vocabulaire

            invalider_apres("comprehension")

            st.session_state.etape = "analyse_comprehension"

            st.rerun()


elif st.session_state.etape == "analyse_comprehension":

    st.subheader("Compréhension enregistrée")

    st.write("### Sujet principal")
    st.write(st.session_state.sujet)

    st.write("### Idées importantes")
    st.write(st.session_state.idees)

    st.write("### Mots ou passages difficiles")
    st.write(st.session_state.vocabulaire)

    if st.button("Modifier mes réponses"):

        st.session_state.etape = "comprehension"
        st.rerun()

    st.divider()

    if not st.session_state.feedback_comprehension:

        if st.button("🤖 Vérifier ma compréhension"):

            instructions = """
Tu vérifies uniquement la compréhension d'une source
par un élève de collège.

Vérifie :
- le sujet principal ;
- les 2 ou 3 idées retenues ;
- les éventuels mots ou passages incompris.

SÉLECTIONNER N'EST PAS DÉFORMER.

Une idée exacte ne doit pas être critiquée
simplement parce que la source permettrait d'en dire davantage.

Si l'élève signale un mot incompris,
explique-le simplement.

Si une erreur importante subsiste :
- ne donne pas la correction ;
- choisis UNE difficulté ;
- pose UNE question permettant à l'élève
  de retrouver lui-même l'information.

Si tout est suffisant, réponds exactement :

COMPRÉHENSION VALIDÉE
Tu as bien compris les idées essentielles de la source.
Tu peux passer à la construction du plan.

Sinon commence exactement par :

À REVOIR
"""

            contenu = f"""
NIVEAU :
{st.session_state.niveau}

SOURCE :
{st.session_state.source}

SUJET :
{st.session_state.sujet}

IDÉES :
{st.session_state.idees}

VOCABULAIRE :
{st.session_state.vocabulaire}
"""

            try:

                with st.spinner(
                    "Le Coach vérifie ta compréhension..."
                ):

                    st.session_state.feedback_comprehension = appel_ia(
                        instructions,
                        contenu
                    )

                st.rerun()

            except Exception as e:

                st.error("Erreur pendant la vérification.")
                st.code(str(e))

    else:

        if est_valide(
            st.session_state.feedback_comprehension,
            "COMPRÉHENSION VALIDÉE"
        ):

            st.success("✅ Compréhension validée")

            if st.button("Construire mon plan"):

                st.session_state.etape = "plan"
                st.rerun()

        else:

            st.subheader("Retour du Coach")

            st.write(
                st.session_state.feedback_comprehension
            )

            if st.button("Reprendre mes réponses"):

                st.session_state.etape = "comprehension"
                st.rerun()


# =========================================================
# PARCOURS LIBRE — THÈME / SUJET / ANGLE
# =========================================================

elif st.session_state.etape == "libre_cadrage":

    st.subheader("Étape 1 — De l'idée à l'angle")

    st.write(
        "Pars du général pour aller vers quelque chose de précis."
    )

    with st.expander("📻 Rappel : thème, sujet et angle"):

        st.write(
            "**Thème** : le domaine général."
        )

        st.write(
            "**Sujet** : un aspect plus précis de ce thème."
        )

        st.write(
            "**Angle** : l'aspect précis du sujet que tu choisis de traiter."
        )

        st.warning(
            "Une chronique ne peut pas tout raconter. "
            "Choisir un angle, c'est choisir l'essentiel."
        )

    libre_theme = st.text_input(
        "Quel est ton thème général ?",
        value=st.session_state.libre_theme
    )

    libre_sujet = st.text_input(
        "Quel sujet précis veux-tu traiter ?",
        value=st.session_state.libre_sujet
    )

    libre_angle = st.text_area(
        "Quel angle veux-tu choisir ? "
        "Qu'est-ce que tu veux surtout faire comprendre ou découvrir ?",
        value=st.session_state.libre_angle,
        height=120
    )

    if st.button("Enregistrer mon idée"):

        if not all([
            libre_theme.strip(),
            libre_sujet.strip(),
            libre_angle.strip()
        ]):

            st.warning(
                "Complète le thème, le sujet et l'angle."
            )

        else:

            st.session_state.libre_theme = libre_theme
            st.session_state.libre_sujet = libre_sujet
            st.session_state.libre_angle = libre_angle
            st.session_state.feedback_angle = ""

            st.session_state.etape = "libre_angle_verif"

            st.rerun()


elif st.session_state.etape == "libre_angle_verif":

    st.subheader("Ton projet de chronique")

    st.write(
        f"**Thème :** {st.session_state.libre_theme}"
    )

    st.write(
        f"**Sujet :** {st.session_state.libre_sujet}"
    )

    st.write(
        f"**Angle :** {st.session_state.libre_angle}"
    )

    if st.button("Modifier mon projet"):

        st.session_state.etape = "libre_cadrage"
        st.rerun()

    st.divider()

    if not st.session_state.feedback_angle:

        if st.button("🤖 Vérifier mon angle"):

            instructions = """
Tu es le Coach d'écriture Radio ISTJ.

Tu vérifies uniquement la relation :

THÈME → SUJET → ANGLE.

Le THÈME est le domaine général.

Le SUJET est un aspect plus précis de ce thème.

L'ANGLE est la direction choisie pour traiter ce sujet :
ce que l'élève veut principalement raconter,
faire comprendre, observer ou découvrir.

L'angle sert surtout à déterminer
dans quelle direction l'élève va faire ses recherches.

Un angle est suffisamment précis lorsque :
- on comprend clairement de quoi la chronique va parler ;
- on comprend quel aspect du sujet sera privilégié ;
- l'élève sait dans quelle direction commencer ses recherches.

Il n'est PAS nécessaire, à ce stade,
de connaître déjà toutes les informations
qui apparaîtront dans la chronique.

NE CONFONDS PAS :
« choisir un angle »
avec
« construire déjà le contenu de la chronique ».

Si l'angle permet déjà de savoir dans quelle direction chercher,
tu dois le valider.

Ne demande PAS à l'élève de préciser dès maintenant :
- quels changements exacts il présentera ;
- quelles personnes exactes il interrogera ;
- quels exemples exacts il utilisera ;
- quelles informations précises il développera,

si ces éléments doivent justement être découverts
pendant les recherches.

EXEMPLE :

THÈME :
La rentrée scolaire

SUJET :
La rentrée 2026 dans notre collège

ANGLE :
Présenter les principaux changements de la rentrée 2026
dans notre collège.

Cet angle est suffisamment précis.
Tu dois donc le VALIDER.

Tu ne dois PAS proposer toi-même une liste de catégories,
de sous-thèmes ou d'exemples qui ne viennent pas de l'élève.

Un angle est réellement trop large si :
- il répète simplement le thème ou le sujet ;
- il permettrait de parler de presque tout ;
- il ne donne aucune direction de recherche.

Avant de répondre « À REVOIR », demande-toi :

« Cet angle permet-il déjà à l'élève
de savoir dans quelle direction commencer ses recherches ? »

Si OUI :
tu dois valider l'angle.

Si thème, sujet et angle sont suffisamment clairs,
réponds exactement :

ANGLE VALIDÉ
Ton sujet et ton angle sont suffisamment précis.
Tu peux commencer tes recherches.

Sinon commence exactement par :

À REVOIR

Puis :
- explique brièvement ce qui reste trop large ;
- pose UNE seule question ouverte ;
- ne propose pas toi-même la réponse ;
- ne donne pas de liste d'exemples.
"""

            contenu = f"""
NIVEAU :
{st.session_state.niveau}

THÈME :
{st.session_state.libre_theme}

SUJET :
{st.session_state.libre_sujet}

ANGLE :
{st.session_state.libre_angle}
"""

            try:

                with st.spinner(
                    "Le Coach examine ton angle..."
                ):

                    st.session_state.feedback_angle = appel_ia(
                        instructions,
                        contenu
                    )

                st.rerun()

            except Exception as e:

                st.error(
                    "Erreur pendant la vérification."
                )

                st.code(str(e))

    else:

        if est_valide(
            st.session_state.feedback_angle,
            "ANGLE VALIDÉ"
        ):

            st.success("✅ Angle validé")

            if st.button("Passer aux recherches"):

                st.session_state.etape = "libre_recherches"
                st.rerun()

        else:

            st.subheader("Retour du Coach")

            st.write(
                st.session_state.feedback_angle
            )

            if st.button("Revoir mon angle"):

                st.session_state.etape = "libre_cadrage"
                st.rerun()


# =========================================================
# PARCOURS LIBRE — RECHERCHES
# =========================================================

elif st.session_state.etape == "libre_recherches":

    st.subheader("Étape 2 — Faire mes recherches")

    st.write(
        "Rassemble maintenant les informations qui pourront servir "
        "à ta chronique."
    )

    st.info(
        "Tu peux utiliser plusieurs sources. "
        "Copie ici tes notes, les informations utiles "
        "et indique d'où elles viennent."
    )

    libre_recherches = st.text_area(
        "Mes recherches et mes sources :",
        value=st.session_state.libre_recherches,
        height=320
    )

    libre_infos = st.text_area(
        "Quelles informations veux-tu surtout retenir pour ta chronique ?",
        value=st.session_state.libre_infos,
        height=180
    )

    if st.button("Enregistrer mes recherches"):

        if not libre_recherches.strip():

            st.warning(
                "Ajoute au moins une source ou des notes de recherche."
            )

        elif not libre_infos.strip():

            st.warning(
                "Indique les informations que tu souhaites retenir."
            )

        else:

            st.session_state.libre_recherches = libre_recherches
            st.session_state.libre_infos = libre_infos
            st.session_state.feedback_recherches = ""

            st.session_state.etape = "libre_recherches_verif"

            st.rerun()


elif st.session_state.etape == "libre_recherches_verif":

    st.subheader("Informations retenues")

    st.write(
        st.session_state.libre_infos
    )

    if st.button("Modifier mes recherches"):

        st.session_state.etape = "libre_recherches"
        st.rerun()

    st.divider()

    if not st.session_state.feedback_recherches:

        if st.button("🤖 Vérifier mes recherches"):

            instructions = """
Tu vérifies le travail de recherche préparatoire
d'un élève pour une chronique radio.

Utilise UNIQUEMENT les documents et notes fournis.

Vérifie principalement :

1. que les informations que l'élève veut retenir
   sont justifiables par ses recherches ;

2. qu'elles correspondent à son angle ;

3. qu'il dispose d'assez de matière pour commencer à organiser
   sa chronique.

SÉLECTIONNER N'EST PAS DÉFORMER.

L'élève n'a pas à utiliser toutes les informations trouvées.

Une observation directe peut constituer une source.

Une information connue ou obtenue dans le collège
peut également être utilisée si elle est présentée comme telle.

Ne demande pas automatiquement une référence bibliographique
complète à cette étape.

Ne rédige jamais la chronique à la place de l'élève.

Si une information retenue n'est pas soutenue par les recherches :
pose UNE question ciblée.

Si le dossier est suffisant, réponds exactement :

RECHERCHES VALIDÉES
Tes recherches donnent suffisamment d'informations pour préparer ta chronique.

Sinon commence exactement par :

À REVOIR
"""

            contenu = f"""
NIVEAU :
{st.session_state.niveau}

THÈME :
{st.session_state.libre_theme}

SUJET :
{st.session_state.libre_sujet}

ANGLE :
{st.session_state.libre_angle}

RECHERCHES :
{st.session_state.libre_recherches}

INFORMATIONS RETENUES :
{st.session_state.libre_infos}
"""

            try:

                with st.spinner(
                    "Le Coach vérifie tes recherches..."
                ):

                    st.session_state.feedback_recherches = appel_ia(
                        instructions,
                        contenu
                    )

                st.rerun()

            except Exception as e:

                st.error(
                    "Erreur pendant la vérification."
                )

                st.code(str(e))

    else:

        if est_valide(
            st.session_state.feedback_recherches,
            "RECHERCHES VALIDÉES"
        ):

            st.success("✅ Recherches validées")

            if st.button(
                "Préparer les informations essentielles"
            ):

                st.session_state.etape = "libre_5w"
                st.rerun()

        else:

            st.subheader("Retour du Coach")

            st.write(
                st.session_state.feedback_recherches
            )

            if st.button("Reprendre mes recherches"):

                st.session_state.etape = "libre_recherches"
                st.rerun()


# =========================================================
# PARCOURS LIBRE — 5W
# =========================================================

elif st.session_state.etape == "libre_5w":

    st.subheader("Étape 3 — Les informations essentielles")

    st.write(
        "Les journalistes utilisent souvent les 5 W pour vérifier "
        "qu'ils disposent des informations utiles."
    )

    st.warning(
        "Ce n'est pas un questionnaire obligatoire : "
        "si une question n'est pas utile à ton angle, tu peux écrire "
        "« Pas nécessaire pour mon angle »."
    )

    libre_what = st.text_area(
        "WHAT ? De quoi parle précisément ta chronique ?",
        value=st.session_state.libre_what
    )

    libre_who = st.text_area(
        "WHO ? Qui est concerné ?",
        value=st.session_state.libre_who
    )

    libre_where = st.text_area(
        "WHERE ? Où cela se passe-t-il ?",
        value=st.session_state.libre_where
    )

    libre_when = st.text_area(
        "WHEN ? Quand cela se passe-t-il ?",
        value=st.session_state.libre_when
    )

    libre_whyhow = st.text_area(
        "WHY / HOW ? Pourquoi ce sujet est-il intéressant ? "
        "Que veux-tu expliquer ou faire comprendre ?",
        value=st.session_state.libre_whyhow,
        height=130
    )

    if st.button("Enregistrer cette préparation"):

        st.session_state.libre_what = libre_what
        st.session_state.libre_who = libre_who
        st.session_state.libre_where = libre_where
        st.session_state.libre_when = libre_when
        st.session_state.libre_whyhow = libre_whyhow

        st.session_state.etape = "plan"

        st.rerun()


# =========================================================
# PLAN — COMMUN AUX DEUX PARCOURS
# =========================================================

elif st.session_state.etape == "plan":

    st.subheader("Construire le plan")

    if st.session_state.parcours == "libre":

        st.info(
            f"**Sujet :** {st.session_state.libre_sujet}\n\n"
            f"**Angle :** {st.session_state.libre_angle}"
        )

        with st.expander("📻 Rappel : écrire pour la radio"):

            st.write(
                "**Court, clair, concis.** "
                "Privilégie les phrases courtes et les idées faciles "
                "à comprendre à la première écoute."
            )

            st.write(
                "Ton introduction peut comporter une **accroche** "
                "qui donne envie de rester à l'écoute."
            )

            st.write(
                "Ton développement doit rester centré sur ton **angle**."
            )

            st.write(
                "Ta conclusion doit apporter une vraie idée de fin."
            )

    else:

        st.write(
            "Indique ce que tu veux faire dans chaque partie. "
            "Tu n'écris pas encore les phrases."
        )

    plan_introduction = st.text_area(
        "Introduction — Que veux-tu faire au début ?",
        value=st.session_state.plan_introduction
    )

    plan_developpement = st.text_area(
        "Développement — Quelles idées veux-tu présenter, et dans quel ordre ?",
        value=st.session_state.plan_developpement,
        height=180
    )

    plan_conclusion = st.text_area(
        "Conclusion — Sur quelle idée veux-tu terminer ?",
        value=st.session_state.plan_conclusion
    )

    if st.session_state.nombre_voix != "1 voix":

        plan_repartition = st.text_area(
            f"Répartition des {st.session_state.nombre_voix} — "
            "Qui intervient dans les différentes parties ?",
            value=st.session_state.plan_repartition,
            height=140
        )

    else:

        plan_repartition = ""

    if st.button("Enregistrer mon plan"):

        if not all([
            plan_introduction.strip(),
            plan_developpement.strip(),
            plan_conclusion.strip()
        ]):

            st.warning(
                "Complète l'introduction, le développement "
                "et la conclusion."
            )

        elif (
            st.session_state.nombre_voix != "1 voix"
            and not plan_repartition.strip()
        ):

            st.warning(
                "Indique comment les voix seront réparties."
            )

        else:

            st.session_state.plan_introduction = plan_introduction
            st.session_state.plan_developpement = plan_developpement
            st.session_state.plan_conclusion = plan_conclusion
            st.session_state.plan_repartition = plan_repartition

            invalider_apres("plan")

            st.session_state.etape = "plan_enregistre"

            st.rerun()


elif st.session_state.etape == "plan_enregistre":

    st.subheader("Plan enregistré")

    st.write("### Introduction")
    st.write(st.session_state.plan_introduction)

    st.write("### Développement")
    st.write(st.session_state.plan_developpement)

    st.write("### Conclusion")
    st.write(st.session_state.plan_conclusion)

    if st.session_state.nombre_voix != "1 voix":

        st.write("### Répartition des voix")
        st.write(st.session_state.plan_repartition)

    if st.button("Modifier mon plan"):

        st.session_state.etape = "plan"
        st.rerun()

    st.divider()

    if not st.session_state.feedback_plan:

        if st.button("🤖 Faire vérifier mon plan"):

            instructions = """
Tu vérifies le plan d'une chronique Radio ISTJ.

Le plan peut être simple.

Vérifie :
- introduction ;
- développement ;
- conclusion ;
- cohérence avec le sujet ;
- cohérence avec l'angle s'il existe ;
- répartition des voix si nécessaire.

Le plan n'est PAS le texte définitif.

Tu ne rédiges aucune phrase à la place de l'élève.

SÉLECTIONNER N'EST PAS DÉFORMER.

Pour 6e-5e :
un plan simple peut suffire.

Pour 4e-3e :
attends davantage de précision et de progression,
sans exiger l'exhaustivité.

Si l'élève suit un parcours libre,
vérifie particulièrement que le développement reste centré
sur l'ANGLE choisi.

Si le plan est suffisant, réponds exactement :

PLAN VALIDÉ
Ton plan est suffisamment clair et organisé.
Tu peux commencer la rédaction de l'introduction.

Sinon commence exactement par :

À REVOIR

Puis traite UNE difficulté prioritaire.
"""

            contenu = f"""
NIVEAU :
{st.session_state.niveau}

FORMAT :
{st.session_state.nombre_voix}

PARCOURS :
{st.session_state.parcours}

DOCUMENTS / RECHERCHES :
{contexte_documentaire()}

PLAN INTRODUCTION :
{st.session_state.plan_introduction}

PLAN DÉVELOPPEMENT :
{st.session_state.plan_developpement}

PLAN CONCLUSION :
{st.session_state.plan_conclusion}

RÉPARTITION :
{st.session_state.plan_repartition}
"""

            try:

                with st.spinner(
                    "Le Coach vérifie ton plan..."
                ):

                    st.session_state.feedback_plan = appel_ia(
                        instructions,
                        contenu
                    )

                st.rerun()

            except Exception as e:

                st.error(
                    "Erreur pendant la vérification."
                )

                st.code(str(e))

    else:

        if est_valide(
            st.session_state.feedback_plan,
            "PLAN VALIDÉ"
        ):

            st.success("✅ Plan validé")

            if st.button("Rédiger mon introduction"):

                st.session_state.etape = "introduction"
                st.rerun()

        else:

            st.subheader("Retour du Coach")

            st.write(
                st.session_state.feedback_plan
            )

            if st.button("Reprendre mon plan"):

                st.session_state.etape = "plan"
                st.rerun()


# =========================================================
# INTRODUCTION — COMMUNE
# =========================================================

elif st.session_state.etape == "introduction":

    st.subheader("Rédiger l'introduction")

    if st.session_state.parcours == "libre":

        st.info(
            "Pense à l'écoute : ton début doit permettre de comprendre "
            "le sujet et, si possible, donner envie d'écouter la suite."
        )

    else:

        st.info(
            "L'introduction doit permettre d'identifier le sujet "
            "et de comprendre son intérêt."
        )

    st.write("### Ton plan")

    st.write(
        st.session_state.plan_introduction
    )

    introduction = st.text_area(
        "Ton introduction :",
        value=st.session_state.introduction,
        height=180
    )

    if st.button("Enregistrer mon introduction"):

        if not introduction.strip():

            st.warning(
                "Écris d'abord ton introduction."
            )

        else:

            st.session_state.introduction = introduction

            invalider_apres("introduction")

            st.session_state.etape = "controle_introduction"

            st.rerun()


elif st.session_state.etape == "controle_introduction":

    st.subheader("Ton introduction")

    st.write(
        st.session_state.introduction
    )

    if st.button("Modifier mon introduction"):

        st.session_state.etape = "introduction"
        st.rerun()

    st.divider()

    if not st.session_state.feedback_introduction:

        if st.button("🤖 Vérifier mon introduction"):

            instructions = REGLES_REDACTION + """

TU CONTRÔLES UNIQUEMENT L'INTRODUCTION.

Elle doit :
- permettre d'identifier le sujet ;
- permettre de comprendre son intérêt.

Dans le parcours libre,
vérifie aussi qu'elle reste cohérente avec l'angle.

Une accroche intéressante est un PLUS,
mais ne refuse pas automatiquement une introduction simple
si elle remplit déjà son rôle.

Pour 6e-5e :
une ou deux phrases simples peuvent suffire.

Ne demande pas automatiquement :
- date ;
- chiffre ;
- lieu plus précis ;
- mécanisme ;
- détail technique ;
- explication qui pourra venir dans le développement.

Pour 4e-3e :
tu peux attendre davantage de contextualisation,
mais l'introduction n'a pas à contenir le développement.

IMPORTANT :

Si le texte contient une phrase qui semble répondre directement
au Coach plutôt qu'à l'auditeur,
comme « oui je confirme », « non je voulais dire »,
ne la considère pas comme une phrase normale de chronique.

Si elle est suffisante, réponds exactement :

INTRODUCTION VALIDÉE
L'introduction remplit son rôle.
Tu peux passer au développement.

Sinon commence exactement par :

À REVOIR
"""

            contenu = f"""
NIVEAU :
{st.session_state.niveau}

PARCOURS :
{st.session_state.parcours}

FORMAT :
{st.session_state.nombre_voix}

DOCUMENTS / RECHERCHES :
{contexte_documentaire()}

PLAN :
{st.session_state.plan_introduction}

INTRODUCTION :
{st.session_state.introduction}
"""

            try:

                with st.spinner(
                    "Le Coach vérifie ton introduction..."
                ):

                    st.session_state.feedback_introduction = appel_ia(
                        instructions,
                        contenu
                    )

                st.rerun()

            except Exception as e:

                st.error(
                    "Erreur pendant la vérification."
                )

                st.code(str(e))

    else:

        if est_valide(
            st.session_state.feedback_introduction,
            "INTRODUCTION VALIDÉE"
        ):

            st.success("✅ Introduction validée")

            if st.button("Passer au développement"):

                st.session_state.etape = "developpement"
                st.rerun()

        else:

            st.subheader("Retour du Coach")

            st.write(
                st.session_state.feedback_introduction
            )

            if st.button("Corriger mon introduction"):

                st.session_state.etape = "introduction"
                st.rerun()


# =========================================================
# DÉVELOPPEMENT — COMMUN
# =========================================================

elif st.session_state.etape == "developpement":

    st.subheader("Rédiger le développement")

    if st.session_state.parcours == "libre":

        st.info(
            f"Reste centré sur ton angle : "
            f"**{st.session_state.libre_angle}**"
        )

    st.write("### Ton plan")

    st.write(
        st.session_state.plan_developpement
    )

    if st.session_state.nombre_voix != "1 voix":

        st.write("### Répartition prévue")

        st.write(
            st.session_state.plan_repartition
        )

    developpement = st.text_area(
        "Ton développement :",
        value=st.session_state.developpement,
        height=340
    )

    if st.button("Enregistrer mon développement"):

        if not developpement.strip():

            st.warning(
                "Écris d'abord ton développement."
            )

        else:

            st.session_state.developpement = developpement

            invalider_apres("developpement")

            st.session_state.etape = "controle_developpement"

            st.rerun()


elif st.session_state.etape == "controle_developpement":

    st.subheader("Ton développement")

    st.write(
        st.session_state.developpement
    )

    if st.button("Modifier mon développement"):

        st.session_state.etape = "developpement"
        st.rerun()

    st.divider()

    if not st.session_state.feedback_developpement:

        if st.button("🤖 Vérifier mon développement"):

            instructions = REGLES_REDACTION + """

TU CONTRÔLES UNIQUEMENT LE DÉVELOPPEMENT.

Le PLAN est le contrat principal de rédaction.

Le développement n'a pas à reprendre
toutes les informations disponibles.

Vérifie :
- fidélité aux recherches ;
- idées prévues dans le plan ;
- clarté à l'écoute ;
- formulation personnelle ;
- cohérence avec l'angle dans le parcours libre.

Pour le parcours libre :
l'élève peut avoir davantage de liberté de ton,
de structure, de description et de transitions.

Ne transforme pas cette liberté en obligation.

=========================================================
DÉVELOPPEMENT ET INFORMATIONS DÉJÀ DONNÉES
=========================================================

Le plan guide la chronique entière.
Il ne faut PAS obliger l'élève à répéter dans le développement
une information déjà clairement et correctement donnée
dans l'INTRODUCTION DÉJÀ VALIDÉE.

Avant de considérer qu'une information prévue dans le plan
du développement est absente, vérifie obligatoirement
si elle apparaît déjà dans l'introduction.

Si l'information est déjà :
- clairement formulée ;
- fidèle à la source ;
- suffisamment précise pour le niveau de l'élève ;

et qu'une nouvelle mention n'apporterait rien,
considère cette information comme DÉJÀ TRAITÉE
dans la chronique.

Tu ne dois PAS demander sa répétition dans le développement.

EXEMPLE OBLIGATOIRE :

Le plan du développement prévoit notamment :

« Présenter la magnitude du séisme principal. »

L'introduction déjà validée dit :

« Un puissant séisme a frappé l'est de l'Indonésie
ce 15 août 2026. Sa magnitude a atteint 7,7. »

Le développement n'a PAS besoin de répéter :

« Le séisme a atteint une magnitude de 7,7. »

La magnitude doit être considérée comme déjà traitée.

En revanche, si le plan prévoit une information
qui n'apparaît ni dans l'introduction
ni dans le développement, elle peut réellement être demandée.

Avant de signaler une information manquante,
pose-toi donc obligatoirement cette question :

« Cette information est-elle réellement absente
de la chronique déjà rédigée,
ou apparaît-elle déjà clairement dans l'introduction ? »

Si elle apparaît déjà clairement dans l'introduction
et qu'une répétition n'apporterait rien :
NE LA DEMANDE PAS.

=========================================================
RÈGLE ESSENTIELLE : PLAN ET NIVEAU DE DÉTAIL
=========================================================

Le niveau de détail exigé dans le développement
doit être déterminé par le PLAN DE L'ÉLÈVE,
et non par la quantité d'informations disponibles
dans la source.

Le mot « comment » dans un plan
ne signifie PAS automatiquement
« décrire toute la procédure technique ».

Si le plan dit seulement qu'il faut expliquer
comment un traitement, un dispositif ou un phénomène fonctionne,
une explication correcte de son PRINCIPE suffit.

Tu ne dois PAS exiger les détails techniques présents
dans la source, tels que :

- les instruments utilisés ;
- le matériel utilisé ;
- les gestes techniques ;
- toutes les étapes d'une procédure ;
- les modalités précises d'implantation ;
- la manière exacte dont un dispositif est guidé ;
- les détails opératoires ;

SAUF si le plan de l'élève prévoit explicitement
de présenter ces détails.

=========================================================
EXEMPLE OBLIGATOIRE DE RAISONNEMENT
=========================================================

Supposons que la source explique précisément
avec quels instruments des bâtonnets contenant du radium 224
sont introduits et guidés dans une tumeur.

Si le plan prévoit simplement :

« Expliquer comment les bâtonnets contenant du radium 224
sont placés dans la tumeur. »

et que l'élève écrit :

« Des bâtonnets contenant du radium 224
sont placés directement dans la tumeur. »

tu ne dois PAS lui demander :
- avec quels instruments ils sont introduits ;
- comment ils sont guidés ;
- comment ils sont répartis dans la tumeur ;
- de décrire la procédure d'implantation.

Ces précisions existent peut-être dans la source,
mais elles ne sont PAS exigées par ce plan.

En revanche, si le plan disait explicitement :

« Expliquer avec quels instruments les bâtonnets
sont introduits et comment ils sont positionnés
à différents endroits de la tumeur »,

alors ces informations devraient effectivement
apparaître dans le développement.

=========================================================
DISTINGUER INFORMATION PRÉVUE ET DÉTAIL SUPPLÉMENTAIRE
=========================================================

Avant de demander une précision absente,
pose-toi obligatoirement cette question :

« Cette information est-elle explicitement prévue par le plan,
ou est-ce seulement un détail supplémentaire présent
dans la source ? »

Si c'est seulement un détail supplémentaire :
NE LE DEMANDE PAS.

Si l'information est explicitement prévue par le plan :
tu peux demander à l'élève de la compléter.

EXEMPLE :

Si le plan prévoit :

« Présenter le caractère expérimental du traitement
et le temps nécessaire pour connaître son efficacité »

mais que le développement dit seulement :

« Cette technique est encore expérimentale »,

alors le délai prévu par le plan manque réellement.

Dans ce cas, tu peux demander à l'élève
de retrouver ce délai dans la source.

Cette situation est différente
d'un détail technique non prévu dans le plan.

=========================================================
RÈGLE D'ARRÊT
=========================================================

Si toutes les idées prévues dans le plan sont :

- présentes ;
- fidèles à la source ;
- suffisamment compréhensibles pour le niveau de l'élève ;

tu DOIS valider le développement.

Tu ne dois PAS chercher ensuite
une nouvelle précision à demander.

Tu ne dois PAS demander :
- un chiffre ;
- un exemple ;
- un instrument ;
- une étape ;
- un détail technique ;
- une précision supplémentaire ;

simplement parce que cette information existe
dans la source.

Si tu constates toi-même dans ton analyse que :

« toutes les idées du plan sont présentes
et les informations sont fidèles »,

tu ne peux PAS ensuite refuser le développement
pour l'absence d'un détail qui n'était pas explicitement
demandé dans le plan.

Dans ce cas :
TU DOIS VALIDER.

=========================================================
NIVEAU
=========================================================

Pour 6e-5e :
quelques informations simples et exactes peuvent suffire.

Pour 4e-3e :
attends davantage de précision et d'explication,
mais toujours dans les limites de ce que prévoit le plan.

Le niveau 4e-3e ne justifie PAS
d'exiger automatiquement tous les détails techniques
présents dans la source.

=========================================================
DIALOGUE AVEC LE COACH
=========================================================

Ne valide pas comme texte radiophonique
une phrase manifestement adressée au Coach,
par exemple :

« oui, je confirme... »

ou

« non, je voulais dire... ».

=========================================================
VALIDATION
=========================================================

Si le développement est suffisant, réponds exactement :

DÉVELOPPEMENT VALIDÉ
Le développement remplit son rôle.
Tu peux passer à la conclusion.

Sinon commence exactement par :

À REVOIR

Traite UNE difficulté prioritaire.
"""

            contenu = f"""
NIVEAU :
{st.session_state.niveau}

PARCOURS :
{st.session_state.parcours}

FORMAT :
{st.session_state.nombre_voix}

DOCUMENTS / RECHERCHES :
{contexte_documentaire()}

INTRODUCTION DÉJÀ VALIDÉE :
{st.session_state.introduction}

PLAN :
{st.session_state.plan_developpement}

RÉPARTITION :
{st.session_state.plan_repartition}

DÉVELOPPEMENT :
{st.session_state.developpement}
"""

            try:

                with st.spinner(
                    "Le Coach vérifie ton développement..."
                ):

                    st.session_state.feedback_developpement = appel_ia(
                        instructions,
                        contenu
                    )

                st.rerun()

            except Exception as e:

                st.error(
                    "Erreur pendant la vérification."
                )

                st.code(str(e))

    else:

        if est_valide(
            st.session_state.feedback_developpement,
            "DÉVELOPPEMENT VALIDÉ"
        ):

            st.success("✅ Développement validé")

            if st.button("Passer à la conclusion"):

                st.session_state.etape = "conclusion"
                st.rerun()

        else:

            st.subheader("Retour du Coach")

            st.write(
                st.session_state.feedback_developpement
            )

            if st.button("Corriger mon développement"):

                st.session_state.etape = "developpement"
                st.rerun()


# =========================================================
# CONCLUSION — COMMUNE
# =========================================================

elif st.session_state.etape == "conclusion":

    st.subheader("Rédiger la conclusion")

    st.write("### Ton plan")

    st.write(
        st.session_state.plan_conclusion
    )

    conclusion = st.text_area(
        "Ta conclusion :",
        value=st.session_state.conclusion,
        height=180
    )

    if st.button("Enregistrer ma conclusion"):

        if not conclusion.strip():

            st.warning(
                "Écris d'abord ta conclusion."
            )

        else:

            st.session_state.conclusion = conclusion

            invalider_apres("conclusion")

            st.session_state.etape = "controle_conclusion"

            st.rerun()


elif st.session_state.etape == "controle_conclusion":

    st.subheader("Ta conclusion")

    st.write(
        st.session_state.conclusion
    )

    if st.button("Modifier ma conclusion"):

        st.session_state.etape = "conclusion"
        st.rerun()

    st.divider()

    if not st.session_state.feedback_conclusion:

        if st.button("🤖 Vérifier ma conclusion"):

            instructions = REGLES_REDACTION + """

TU CONTRÔLES UNIQUEMENT LA CONCLUSION.

Elle doit apporter une vraie idée de fin.

Elle peut :
- rappeler l'essentiel ;
- ouvrir sur une perspective ;
- présenter un enjeu ;
- montrer une incertitude ;
- donner une courte appréciation personnelle identifiable.

Pour 6e-5e :
une phrase simple peut suffire.

Dans le parcours libre :
elle doit rester cohérente avec l'angle choisi.

Ne demande pas une information supplémentaire
simplement pour enrichir le texte.

=========================================================
CONCLUSION ET RAPPEL DU PLAN
=========================================================

La conclusion doit respecter l'IDÉE GÉNÉRALE
prévue dans le plan.

Mais elle n'a PAS à répéter
tous les détails déjà expliqués dans le développement.

Si le plan prévoit de terminer sur une idée
qui a déjà été expliquée dans le développement,
un rappel plus général de cette idée peut suffire.

La conclusion doit terminer la chronique,
pas refaire le développement.

=========================================================
EXEMPLE OBLIGATOIRE
=========================================================

Supposons que le plan prévoit :

« Terminer en rappelant que l'Indonésie reste particulièrement
exposée aux séismes en raison de sa situation
sur la ceinture de feu du Pacifique. »

Et supposons que le développement a déjà expliqué :

« Les séismes sont fréquents en Indonésie.
Le pays se trouve sur la ceinture de feu du Pacifique,
une région où l'activité sismique et volcanique est importante. »

Alors une conclusion comme :

« Ce séisme rappelle à quel point l'Indonésie
reste exposée à ce type de catastrophe. »

respecte suffisamment l'idée générale du plan.

Tu ne dois PAS exiger que l'élève répète
« ceinture de feu du Pacifique » dans la conclusion,
car cette explication a déjà été donnée
dans le développement.

=========================================================
VÉRIFIER CE QUI A DÉJÀ ÉTÉ DIT
=========================================================

Avant de refuser une conclusion
parce qu'un élément précis du plan
n'apparaît pas à nouveau dans la conclusion,
regarde le DÉVELOPPEMENT DÉJÀ VALIDÉ.

Pose-toi obligatoirement cette question :

« Le détail demandé par le plan
a-t-il déjà été correctement expliqué
dans le développement ? »

Si OUI :

vérifie seulement que la conclusion
rappelle clairement l'idée générale correspondante.

Si elle le fait :
TU DOIS considérer le plan comme respecté.

Tu ne dois PAS obliger l'élève
à répéter une explication déjà donnée.

=========================================================
RÉPÉTITIONS
=========================================================

Une conclusion peut rappeler brièvement
une idée du développement.

Mais elle ne doit pas répéter
une explication entière avec le même niveau de détail.

Un rappel général est donc préférable
à une répétition complète.

Ne sanctionne pas une conclusion
parce qu'elle est plus générale que le plan,
si le détail prévu par ce plan
a déjà été correctement traité auparavant.

=========================================================
ATTENTION AU DIALOGUE AVEC LE COACH
=========================================================

Le texte de conclusion doit contenir uniquement
ce qui sera dit à l'auditeur.

Une phrase comme :

« Oui, je confirme bien que l'interview sera en direct »

est une réponse adressée au Coach.

Elle ne doit PAS être validée comme phrase de chronique.

Si l'élève veut annoncer réellement
que l'interview sera en direct,
cette information doit apparaître naturellement
dans une phrase destinée aux auditeurs.

Ne rédige pas cette phrase à sa place.

Si une information nouvelle concernant un événement futur
apparaît dans la conclusion,
tu peux demander à l'élève de vérifier qu'elle est exacte.

Mais sa réponse de confirmation ne doit pas ensuite
faire partie du texte destiné à l'antenne.

=========================================================
RÈGLE D'ARRÊT
=========================================================

Si :

- la conclusion apporte une vraie idée de fin ;
- elle respecte l'idée générale du plan ;
- les détails manquants dans la conclusion
  ont déjà été correctement expliqués dans le développement ;
- elle reste fidèle aux documents ;

tu DOIS valider.

Ne demande pas ensuite de répéter
un détail simplement parce qu'il apparaissait
dans la formulation du plan.

=========================================================
VALIDATION
=========================================================

Si elle est suffisante, réponds exactement :

CONCLUSION VALIDÉE
La conclusion apporte une véritable idée de fin.
Tu peux passer aux sources utilisées.

Sinon commence exactement par :

À REVOIR
"""

            contenu = f"""
NIVEAU :
{st.session_state.niveau}

PARCOURS :
{st.session_state.parcours}

FORMAT :
{st.session_state.nombre_voix}

DOCUMENTS / RECHERCHES :
{contexte_documentaire()}

PLAN DE CONCLUSION :
{st.session_state.plan_conclusion}

DÉVELOPPEMENT DÉJÀ VALIDÉ :
{st.session_state.developpement}

CONCLUSION :
{st.session_state.conclusion}
"""

            try:

                with st.spinner(
                    "Le Coach vérifie ta conclusion..."
                ):

                    st.session_state.feedback_conclusion = appel_ia(
                        instructions,
                        contenu
                    )

                st.rerun()

            except Exception as e:

                st.error(
                    "Erreur pendant la vérification."
                )

                st.code(str(e))

    else:

        if est_valide(
            st.session_state.feedback_conclusion,
            "CONCLUSION VALIDÉE"
        ):

            st.success("✅ Conclusion validée")

            if st.button(
                "Indiquer mes sources"
                if st.session_state.parcours == "libre"
                else "Indiquer mes références"
            ):

                st.session_state.etape = "references"
                st.rerun()

        else:

            st.subheader("Retour du Coach")

            st.write(
                st.session_state.feedback_conclusion
            )

            if st.button("Corriger ma conclusion"):

                st.session_state.etape = "conclusion"
                st.rerun()


# =========================================================
# SOURCES / RÉFÉRENCES
# =========================================================

elif st.session_state.etape == "references":

    if st.session_state.parcours == "guide":

        st.subheader("Références")

        st.write(
            "Retrouve toi-même les références dans la source."
        )

        st.info(
            "Si une information n'est pas indiquée, "
            "écris « Non indiqué »."
        )

        ref_auteur = st.text_input(
            "Auteur :",
            value=st.session_state.ref_auteur
        )

        ref_titre = st.text_input(
            "Titre :",
            value=st.session_state.ref_titre
        )

        ref_media = st.text_input(
            "Média :",
            value=st.session_state.ref_media
        )

        ref_date = st.text_input(
            "Date :",
            value=st.session_state.ref_date
        )

        if st.button("Enregistrer mes références"):

            if not all([
                ref_auteur.strip(),
                ref_titre.strip(),
                ref_media.strip(),
                ref_date.strip()
            ]):

                st.warning(
                    "Complète les quatre champs."
                )

            else:

                st.session_state.ref_auteur = ref_auteur
                st.session_state.ref_titre = ref_titre
                st.session_state.ref_media = ref_media
                st.session_state.ref_date = ref_date

                invalider_apres("references")

                st.session_state.etape = "controle_references"

                st.rerun()

    else:

        st.subheader("Sources utilisées")

        st.write(
            "Indique les sources que tu as réellement utilisées "
            "pour préparer cette chronique."
        )

        st.info(
            "Une source peut être un article, un site, un document, "
            "une observation directe, une information obtenue dans le collège, "
            "un témoignage ou une interview déjà réalisée."
        )

        st.warning(
            "Une interview seulement prévue ne doit pas encore être "
            "présentée comme une source utilisée."
        )

        libre_references = st.text_area(
            "Mes sources utilisées :",
            value=st.session_state.libre_references,
            height=220,
            placeholder=(
                "Exemples :\n"
                "- Observation directe : travaux de rénovation de la cour, rentrée 2026.\n"
                "- Information interne au collège : arrivée de nouveaux enseignants, rentrée 2026.\n"
                "- Site / article : auteur ou organisme, titre, média, date, lien."
            )
        )

        if st.button("Enregistrer mes sources"):

            if not libre_references.strip():

                st.warning(
                    "Indique au moins une source utilisée."
                )

            else:

                st.session_state.libre_references = libre_references

                invalider_apres("references")

                st.session_state.etape = "controle_references"

                st.rerun()


elif st.session_state.etape == "controle_references":

    if st.session_state.parcours == "guide":

        st.subheader("Tes références")

    else:

        st.subheader("Tes sources utilisées")

    st.write(
        references_affichees()
    )

    if st.button(
        "Modifier mes références"
        if st.session_state.parcours == "guide"
        else "Modifier mes sources"
    ):

        st.session_state.etape = "references"
        st.rerun()

    st.divider()

    if not st.session_state.feedback_references:

        if st.button(
            "🤖 Vérifier mes références"
            if st.session_state.parcours == "guide"
            else "🤖 Vérifier mes sources"
        ):

            instructions = """
Tu vérifies uniquement les sources ou références
d'une chronique Radio ISTJ.

=========================================================
PARCOURS GUIDÉ
=========================================================

Dans le parcours guidé :
vérifie auteur, titre, média et date
par rapport à la source fournie.

=========================================================
RÈGLE ABSOLUE SUR LE TITRE D'UN ARTICLE
=========================================================

Pour identifier le titre d'un article,
utilise en priorité le TITRE EXPLICITEMENT AFFICHÉ
dans le document ou sur la page de l'article.

Tu ne dois JAMAIS déduire,
reconstituer ou contester le titre
à partir du texte contenu dans l'URL.

Une URL peut conserver :
- un ancien titre ;
- une ancienne formulation ;
- un ancien bilan ;
- un ancien nombre ;
- un ancien état de l'actualité ;

même si l'article a ensuite été mis à jour
et que son titre visible a changé.

Le texte contenu dans une URL
n'est donc PAS une référence fiable
pour déterminer le titre actuel de l'article.

Si le titre explicitement affiché dans le document
est différent du texte apparaissant dans l'URL :

LE TITRE AFFICHÉ DANS LE DOCUMENT FAIT FOI.

Tu dois l'accepter comme titre de référence
si l'élève l'a correctement recopié.

=========================================================
EXEMPLE OBLIGATOIRE
=========================================================

Supposons qu'un document affiche le titre :

« Un puissant séisme de magnitude 7,7
fait au moins 40 morts »

mais que l'URL du même article contienne encore :

« fait-au-moins-deux-morts-alerte-au-tsunami-levee »

Tu ne dois PAS considérer cela comme une incohérence
dans les références de l'élève.

L'URL peut avoir été créée
lors d'une version antérieure de l'article.

Si l'élève a recopié le titre visible :

« Un puissant séisme de magnitude 7,7
fait au moins 40 morts »

ce titre doit être considéré comme correct.

Ne demande PAS à l'élève de vérifier
le titre à partir du texte de l'URL.

=========================================================
AUTRES INFORMATIONS DE RÉFÉRENCE
=========================================================

Pour l'auteur :
utilise l'auteur ou l'organisme explicitement affiché.

Pour le média :
utilise le nom du média explicitement identifiable.

Pour la date :
utilise la date explicitement affichée dans la source.

Une éventuelle modification ultérieure de l'article
ne rend pas automatiquement la date de publication incorrecte.

=========================================================
PARCOURS LIBRE
=========================================================

Dans le parcours libre,
le niveau de référencement doit rester adapté
à un travail de collégien en journalisme radio.

Une source peut être :

- une observation directe ;
- une information obtenue ou connue dans le collège ;
- un document ;
- un article ;
- un site internet ;
- un témoignage ;
- une interview DÉJÀ réalisée.

Une source n'a pas besoin d'être présentée
comme une référence universitaire.

L'objectif est seulement :
- de comprendre d'où vient l'information ;
- de pouvoir distinguer une information observée,
  obtenue, lue ou entendue ;
- de permettre raisonnablement de retrouver
  une source documentaire lorsqu'il s'agit d'un article ou d'un site.

=========================================================
OBSERVATIONS DIRECTES
=========================================================

Une formulation comme :

« Observation directe : travaux de rénovation de la cour,
rentrée 2026 »

peut être suffisante.

N'exige PAS automatiquement :
- le jour exact ;
- l'heure ;
- les noms des élèves ayant observé ;
- les modalités de l'observation.

=========================================================
INFORMATIONS INTERNES AU COLLÈGE
=========================================================

Une formulation comme :

« Information interne au collège :
arrivée de nouveaux enseignants, rentrée 2026 »

peut être acceptée pour une chronique scolaire simple.

N'exige pas systématiquement :
- le nom exact de la personne ayant donné l'information ;
- une date précise ;
- un document administratif ;

sauf si l'information est contestable,
très précise ou nécessite réellement une vérification supplémentaire.

=========================================================
EXPÉRIENCE DES ÉLÈVES
=========================================================

Une expérience collective ou une observation générale
peut être utilisée si elle est présentée clairement comme telle.

N'exige pas automatiquement :
- le nom des élèves ;
- leur classe exacte ;
- une méthode d'enquête ;
- des modalités détaillées.

Ne transforme pas une chronique scolaire
en travail de recherche académique.

=========================================================
INTERVIEWS
=========================================================

Une interview DÉJÀ réalisée peut être une source.

Dans ce cas,
il est utile d'indiquer au minimum :
- la personne interrogée ;
- son rôle ;
- si possible la date ou le contexte.

En revanche :

UNE INTERVIEW SEULEMENT PRÉVUE
NE PEUT PAS ÊTRE PRÉSENTÉE
COMME UNE SOURCE DÉJÀ UTILISÉE.

Si elle est seulement annoncée pour plus tard,
elle peut apparaître dans la chronique
comme une future interview,
mais pas dans la liste des sources utilisées.

=========================================================
ARTICLES / SITES / DOCUMENTS
=========================================================

Pour une source documentaire,
essaie de vérifier qu'elle peut être retrouvée
avec suffisamment d'informations :

- auteur ou organisme si disponible ;
- titre affiché dans le document ;
- média ou site ;
- date si disponible ;
- lien si l'élève l'a.

RAPPEL :

Le TITRE AFFICHÉ a priorité
sur le texte éventuellement contenu dans l'URL.

N'exige pas un élément qui n'existe pas.

=========================================================
RÈGLE DE PROPORTION
=========================================================

Avant de demander une précision,
pose-toi cette question :

« Cette précision est-elle nécessaire
pour comprendre d'où vient l'information,
ou rendrait-elle seulement la référence plus complète ? »

Si elle rendrait seulement la référence plus complète :
NE LA DEMANDE PAS.

=========================================================
VALIDATION
=========================================================

Si les sources sont suffisamment identifiables
et correspondent aux recherches réellement utilisées,
réponds exactement :

RÉFÉRENCES VALIDÉES
Les références correspondent aux sources utilisées.

Sinon commence exactement par :

À REVOIR

Puis :
- signale seulement les problèmes réellement importants ;
- ne transforme pas l'exercice en bibliographie universitaire ;
- ne demande pas des précisions inutiles ;
- n'invente jamais une source à la place de l'élève ;
- ne conteste jamais un titre affiché uniquement
  parce que l'URL contient une autre formulation.
"""

            contenu = f"""
PARCOURS :
{st.session_state.parcours}

DOCUMENTS / RECHERCHES :
{contexte_documentaire()}

SOURCES / RÉFÉRENCES DONNÉES PAR L'ÉLÈVE :
{references_affichees()}
"""

            try:

                with st.spinner(
                    "Le Coach vérifie les sources..."
                    if st.session_state.parcours == "libre"
                    else "Le Coach vérifie les références..."
                ):

                    st.session_state.feedback_references = appel_ia(
                        instructions,
                        contenu
                    )

                st.rerun()

            except Exception as e:

                st.error(
                    "Erreur pendant la vérification."
                )

                st.code(str(e))

    else:

        if est_valide(
            st.session_state.feedback_references,
            "RÉFÉRENCES VALIDÉES"
        ):

            if st.session_state.parcours == "guide":

                st.success("✅ Références validées")

            else:

                st.success("✅ Sources validées")

            if st.button("Assembler ma chronique"):

                st.session_state.chronique = assembler_chronique()

                st.session_state.feedback_final = ""

                st.session_state.etape = "chronique_assemblee"

                st.rerun()

        else:

            st.subheader("Retour du Coach")

            st.write(
                st.session_state.feedback_references
            )

            if st.button(
                "Corriger mes références"
                if st.session_state.parcours == "guide"
                else "Corriger mes sources"
            ):

                st.session_state.etape = "references"
                st.rerun()


# =========================================================
# ASSEMBLAGE
# =========================================================

elif st.session_state.etape == "chronique_assemblee":

    st.subheader("Chronique assemblée")

    st.success(
        "La chronique a été assemblée uniquement "
        "avec les textes que tu as écrits."
    )

    st.info(
        "Les sources ne font pas partie du texte à lire à l'antenne. "
        "Elles seront ajoutées séparément dans le PDF."
    )

    st.text_area(
        "Texte à lire à l'antenne :",
        value=st.session_state.chronique,
        height=460,
        disabled=True
    )

    if st.button("🔎 Lancer le contrôle final"):

        st.session_state.etape = "controle_final"
        st.rerun()


# =========================================================
# CONTRÔLE FINAL INDÉPENDANT
# =========================================================

elif st.session_state.etape == "controle_final":

    st.subheader("Contrôle final")

    if not st.session_state.feedback_final:

        instructions = """
Tu réalises le CONTRÔLE FINAL INDÉPENDANT
d'une chronique Radio ISTJ.

Tu disposes séparément :
- de l'introduction ;
- du développement ;
- de la conclusion ;
- des sources / références ;
- du texte complet destiné à l'antenne.

Tu ne réécris rien.
Tu ne cherches pas à améliorer le texte.

Tu détectes uniquement les problèmes
qui rendent une correction réellement nécessaire.

=========================================================
1. FIDÉLITÉ
=========================================================

Toute information factuelle doit être justifiable
par les documents, notes, observations ou recherches fournis.

SÉLECTIONNER N'EST PAS DÉFORMER.

L'omission d'informations n'est pas une erreur.

=========================================================
2. INFORMATION INVENTÉE
=========================================================

Signale un fait qui n'apparaît pas dans les recherches
et ne peut pas raisonnablement en être déduit.

=========================================================
3. EXACTITUDE
=========================================================

Vérifie les nombres, dates, lieux, noms
et autres données effectivement utilisées.

L'absence d'un détail n'est pas une erreur
simplement parce qu'il existe dans une source.

=========================================================
4. TITRES ET URL
=========================================================

Lorsqu'une référence comporte un article :

le titre explicitement affiché dans la source
a priorité sur le texte contenu dans l'URL.

Une URL peut conserver un ancien titre
après la mise à jour d'un article.

Ne signale donc PAS une erreur
si le titre affiché dans le document
est correctement recopié par l'élève,
même si l'URL contient une formulation différente.

Ne reconstitue jamais le titre à partir de l'URL.

=========================================================
5. PLAGIAT
=========================================================

Les faits précis peuvent naturellement être identiques
à ceux de la source.

Signale seulement une reprise vraiment trop proche :
- phrase entière ou presque entière ;
- même construction avec presque les mêmes mots ;
- formulation clairement reconnaissable de la source.

=========================================================
6. CLARTÉ
=========================================================

Signale uniquement ce qui gêne réellement
la compréhension à la première écoute.

Une phrase simple ou scolaire n'est pas un problème
si elle reste compréhensible.

=========================================================
7. RÉPÉTITIONS ENTRE LES PARTIES
=========================================================

Compare explicitement :

- INTRODUCTION ;
- DÉVELOPPEMENT ;
- CONCLUSION.

Une répétition légère peut être normale.

Par exemple :
- annoncer une idée dans l'introduction ;
- la développer ensuite ;
- la rappeler brièvement dans la conclusion

est parfaitement acceptable.

NE SIGNALE PAS cela.

En revanche,
signale une répétition si deux passages disent pratiquement
la même chose avec le même niveau de détail,
sans apporter de nouvelle information,
et que cela rend la chronique manifestement redondante.

Pour un élève de 6e-5e,
une petite répétition de vocabulaire ou d'idée est acceptable.

Ne signale que les répétitions vraiment gênantes.

=========================================================
8. META-DIALOGUE AVEC LE COACH
=========================================================

C'est une vérification OBLIGATOIRE.

Le texte destiné à l'antenne ne doit pas contenir
des phrases qui ont manifestement été écrites
uniquement pour répondre au Coach.

Exemples :

« Oui, je confirme que... »

« Oui, je confirme bien que... »

« Non, je voulais dire... »

« Comme je te l'ai expliqué... »

« Je confirme que cette interview sera en direct. »

Une telle phrase est du META-DIALOGUE,
pas une phrase destinée aux auditeurs.

Si elle apparaît dans la chronique finale,
tu dois la signaler.

ATTENTION :

Une information contenue dans cette phrase
peut être parfaitement vraie.

Le problème n'est alors PAS l'information elle-même.

Le problème est que la phrase est formulée
comme une réponse au Coach
et non comme une phrase de chronique.

L'élève doit lui-même retirer la phrase
ou intégrer l'information naturellement
dans son texte si elle est utile.

Tu ne rédiges jamais cette nouvelle formulation à sa place.

=========================================================
9. QUALITÉ RADIO
=========================================================

Utilise un seuil minimal :

COURT
CLAIR
CONCIS.

Une chronique n'a pas à être parfaite.

Dans le parcours libre :
vérifie également que la chronique reste globalement
cohérente avec l'angle choisi.

Une accroche spectaculaire,
des images mentales
ou un habillage sonore
sont des possibilités,
pas des obligations.

=========================================================
10. SOURCES
=========================================================

Les sources sont transmises séparément.

Elles ne font PAS partie du texte destiné à être lu à l'antenne.

Dans le parcours libre,
les sources peuvent être :

- observation directe ;
- information interne au collège ;
- document ou site ;
- témoignage ;
- interview déjà réalisée.

N'exige pas un référencement universitaire.

Une interview seulement prévue
ne doit pas être présentée comme une source déjà utilisée.

=========================================================
11. NIVEAU
=========================================================

Pour 6e-5e :

- accepte des phrases simples ;
- accepte une organisation simple ;
- accepte quelques idées essentielles ;
- tolère de petites répétitions si elles ne gênent pas vraiment l'écoute.

Pour 4e-3e :

attends davantage :
- de précision ;
- de progression ;
- de liens entre les idées ;

sans exiger l'exhaustivité.

=========================================================
12. TEST DE DÉCISION
=========================================================

Avant de signaler chaque problème,
demande-toi :

« Cette correction est-elle indispensable
pour rendre la chronique diffusable,
ou rendrait-elle seulement le texte meilleur ? »

Si elle rendrait seulement le texte meilleur :
NE LA SIGNALE PAS.

Ne cherche pas une chronique parfaite.

=========================================================
13. VALIDATION
=========================================================

Si aucune correction obligatoire ne subsiste,
réponds EXACTEMENT :

VALIDÉ
La chronique peut passer à l'étape suivante.

=========================================================
14. SI UNE CORRECTION EST NÉCESSAIRE
=========================================================

Commence EXACTEMENT par :

À CORRIGER

Puis utilise ce format :

Problème : [INFORMATION NON FIDÈLE /
INFORMATION INVENTÉE /
CLARTÉ /
PLAGIAT /
RÉPÉTITION GÊNANTE /
META-DIALOGUE /
QUALITÉ RADIO INSUFFISANTE /
SOURCE]

Passage concerné : "[citation exacte]"

Explication : [courte et compréhensible par un collégien]

Consigne : [ce que l'élève doit vérifier ou corriger lui-même]

Ne rédige jamais la correction.

Si plusieurs vrais problèmes subsistent,
tu peux les signaler séparément.

Ne mentionne pas les éléments corrects.
"""

        contenu = f"""
NIVEAU :
{st.session_state.niveau}

PARCOURS :
{st.session_state.parcours}

FORMAT :
{st.session_state.nombre_voix}

DOCUMENTS / RECHERCHES :
{contexte_documentaire()}

ANGLE DU PARCOURS LIBRE :
{st.session_state.libre_angle if st.session_state.parcours == "libre" else "Non applicable"}

=========================================================
INTRODUCTION
=========================================================

{st.session_state.introduction}

=========================================================
DÉVELOPPEMENT
=========================================================

{st.session_state.developpement}

=========================================================
CONCLUSION
=========================================================

{st.session_state.conclusion}

=========================================================
SOURCES / RÉFÉRENCES
=========================================================

{references_affichees()}

=========================================================
TEXTE COMPLET DESTINÉ À L'ANTENNE
=========================================================

{st.session_state.chronique}
"""

        try:

            with st.spinner(
                "Contrôle final de la chronique..."
            ):

                st.session_state.feedback_final = appel_ia(
                    instructions,
                    contenu
                )

            st.rerun()

        except Exception as e:

            st.error(
                "Erreur pendant le contrôle final."
            )

            st.code(str(e))

    else:

        if est_valide(
            st.session_state.feedback_final,
            "VALIDÉ"
        ):

            st.success("✅ Chronique validée")

            st.write(
                "La chronique a passé le contrôle final."
            )

            st.text_area(
                "Texte validé à lire à l'antenne :",
                value=st.session_state.chronique,
                height=430,
                disabled=True
            )

            st.caption(
                "Les sources sont conservées séparément "
                "et apparaîtront dans le PDF."
            )

            st.divider()

            st.subheader("📄 PDF Radio ISTJ")

            try:

                pdf = generer_pdf()

                st.download_button(
                    label="📥 Télécharger le PDF Radio ISTJ",
                    data=pdf,
                    file_name="chronique_radio_istj.pdf",
                    mime="application/pdf",
                    use_container_width=True
                )

            except Exception as e:

                st.error(
                    "Le PDF n'a pas pu être généré."
                )

                st.code(str(e))

        else:

            st.error(
                "La chronique doit encore être corrigée."
            )

            st.write(
                st.session_state.feedback_final
            )

            st.divider()

            st.write(
                "**Choisis la partie à corriger :**"
            )

            col1, col2 = st.columns(2)

            with col1:

                if st.button("Corriger l'introduction"):

                    st.session_state.feedback_introduction = ""
                    st.session_state.feedback_final = ""
                    st.session_state.etape = "introduction"

                    st.rerun()

                if st.button("Corriger la conclusion"):

                    st.session_state.feedback_conclusion = ""
                    st.session_state.feedback_final = ""
                    st.session_state.etape = "conclusion"

                    st.rerun()

            with col2:

                if st.button("Corriger le développement"):

                    st.session_state.feedback_developpement = ""
                    st.session_state.feedback_final = ""
                    st.session_state.etape = "developpement"

                    st.rerun()

                if st.button(
                    "Corriger les références"
                    if st.session_state.parcours == "guide"
                    else "Corriger les sources"
                ):

                    st.session_state.feedback_references = ""
                    st.session_state.feedback_final = ""
                    st.session_state.etape = "references"

                    st.rerun()
