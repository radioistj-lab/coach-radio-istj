"""Lecture locale des PDF pour le parcours guidé de Coach Radio.

Le PDF n'est pas envoyé à un service externe par ce module :
seul son texte est placé dans la source du projet, comme un copier-coller.
"""
from io import BytesIO
import re

from pypdf import PdfReader

TAILLE_MAX = 10 * 1024 * 1024
PAGES_MAX = 25
CARACTERES_MAX = 60000

def extraire_source_pdf(contenu: bytes) -> tuple[str, int]:
    """Renvoie (texte intégral avec références, nombre de pages)."""
    if not contenu:
        raise ValueError("Le fichier PDF est vide.")
    if len(contenu) > TAILLE_MAX:
        raise ValueError("Ce PDF dépasse 10 Mo. Utilise un fichier plus léger.")

    try:
        pdf = PdfReader(BytesIO(contenu), strict=False)
        if pdf.is_encrypted:
            raise ValueError("Ce PDF est protégé par un mot de passe.")
        nombre_pages = len(pdf.pages)
        if nombre_pages == 0:
            raise ValueError("Ce PDF ne contient aucune page.")
        if nombre_pages > PAGES_MAX:
            raise ValueError("Ce PDF contient plus de 25 pages. Choisis un article plus court.")

        textes = []
        nombre_caracteres = 0
        for page in pdf.pages:
            extrait = page.extract_text() or ""
            extrait = extrait.replace("\x00", "").replace("\r", "\n")
            # Éliminer seulement les en-têtes et compteurs de pages RadioBoard.
            # Ne jamais supprimer l'auteur, la date ni l'URL de la source.
            lignes = [
                ligne.strip()
                for ligne in extrait.splitlines()
                if not re.fullmatch(
                    r"RADIO ISTJ\s*[·/|]\s*(?:RESSOURCES DOCUMENTAIRES|\d+\s*/\s*\d+)",
                    ligne.strip(), flags=re.IGNORECASE
                )
            ]
            texte_page = "\n".join(lignes).strip()
            if texte_page:
                textes.append(texte_page)
                nombre_caracteres += len(texte_page)
            if nombre_caracteres > CARACTERES_MAX:
                raise ValueError(
                    "Le document dépasse 60 000 caractères. "
                    "Choisis une source plus courte pour préparer ta chronique."
                )

        texte = "\n\n".join(textes).strip()
        if len(texte) < 80:
            raise ValueError(
                "Je n'ai pas trouvé suffisamment de texte dans ce PDF. "
                "S'il s'agit d'un scan ou d'une photo, il faut d'abord "
                "un PDF avec du texte sélectionnable."
            )
        return texte, nombre_pages
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(
            "Impossible de lire ce PDF. Vérifie qu'il n'est pas endommagé."
        ) from exc
