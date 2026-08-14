#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_pack.py — Convertit un fichier JSON exporté par l'arborescence à histoires
en pack "Archive" natif STUdio (Lunii).

Sous-commandes :
    kit      Génère les fichiers texte des audios à produire.
    build    Assemble le pack ZIP final.
    script   Génère une feuille de lecture continue (Audacity).

Format source : marian-m12l/studio (ArchiveStoryPackWriter.java,
    web-ui/javascript/src/utils/writer.js et sample.js lus directement).
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import unicodedata
import uuid
import zipfile


# ---------------------------------------------------------------------------
# Utilitaires partagés
# ---------------------------------------------------------------------------

def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return text[:80] or "sans-titre"


def alter_uuid(u: str, suffix: str) -> str:
    return u[: -len(suffix)] + suffix


def ensure_mp3(src: str, dst: str) -> None:
    """Normalise tout format audio en MP3 44100 Hz mono (format attendu par la Lunii)."""
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", src,
         "-ar", "44100", "-ac", "1", "-codec:a", "libmp3lame", "-qscale:a", "4", dst],
        check=True,
    )


def ensure_image(src: str, dst: str) -> None:
    """Redimensionne toute image en PNG 320×240."""
    from PIL import Image
    Image.open(src).convert("RGB").resize((320, 240)).save(dst, format="PNG")


# ---------------------------------------------------------------------------
# Validation et chargement de l'arborescence
# ---------------------------------------------------------------------------

def load_arborescence(path: str):
    """
    Charge et valide le fichier JSON.

    Lève SystemExit si :
    - Pas exactement un point de départ (root unique).
    - Un next ou targetId référence un bloc inexistant.
    - Deux passages produisent le même slug (collision).
    """
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    blocks = data["blocks"]
    all_ids = set(blocks)

    # Validation des références
    for bid, b in blocks.items():
        if b["type"] == "carrefour":
            for opt in b["options"]:
                tid = opt.get("targetId")
                if tid and tid not in all_ids:
                    sys.exit(f"ERREUR : le bloc '{bid}' référence un targetId inexistant : '{tid}'")
        elif b.get("next") and b["next"] not in all_ids:
            sys.exit(f"ERREUR : le bloc '{bid}' référence un next inexistant : '{b['next']}'")

    # Détection du root unique
    referenced = set()
    for b in blocks.values():
        if b["type"] == "carrefour":
            referenced.update(o["targetId"] for o in b["options"] if o.get("targetId"))
        elif b.get("next"):
            referenced.add(b["next"])
    roots = [i for i in all_ids if i not in referenced]
    if len(roots) != 1:
        sys.exit(f"ERREUR : {len(roots)} point(s) de départ détecté(s) — il en faut exactement un.")

    return blocks, roots[0]


def needed_audios(blocks: dict, titre: str) -> dict:
    """
    Retourne un dict ordonné slug → (texte, description).

    Les slugs des récits et questions incluent les 6 derniers caractères du bid.
    Les slugs des réponses incluent aussi le bid[-6:] pour éviter les collisions
    entre réponses homonymes dans des carrefours différents.
    Lève SystemExit en cas de collision de slug.
    """
    items = [("couverture_titre", titre, "Titre du pack (écran d'accueil de la Lunii)")]
    for bid, b in blocks.items():
        suffix = bid[-6:]
        if b["type"] == "recit":
            items.append((
                f"recit_{slugify(b['title'])}_{suffix}",
                b["text"],
                f"Récit : {b['title']}",
            ))
        else:
            question = b.get("question") or b["title"]
            items.append((
                f"question_{slugify(b['title'])}_{suffix}",
                question,
                f"Question : {b['title']}",
            ))
            for opt in b["options"]:
                if opt.get("targetId"):
                    items.append((
                        f"reponse_{slugify(opt['label'])}_{suffix}",
                        opt["label"],
                        f"Réponse : {opt['label']}",
                    ))

    result: dict = {}
    for slug, text, desc in items:
        if slug in result:
            sys.exit(
                f"ERREUR : collision de slug '{slug}'. Deux passages produisent le même nom de fichier."
            )
        result[slug] = (text, desc)
    return result


# ---------------------------------------------------------------------------
# Moteurs TTS
# ---------------------------------------------------------------------------

def tts_dispatch(text: str, dst: str, engine: str, passage_type: str = "story") -> None:
    """Dispatche vers le moteur TTS demandé. passage_type réservé pour usage futur."""
    if engine == "espeak":
        _tts_espeak(text, dst)
    elif engine == "google":
        _tts_google(text, dst)
    elif engine == "elevenlabs":
        _tts_elevenlabs(text, dst)
    elif engine == "kokoro":
        _tts_kokoro(text, dst)
    else:
        raise RuntimeError(f"Moteur TTS inconnu : {engine}")


def _tts_espeak(text: str, dst: str) -> None:
    wav = dst + ".wav"
    subprocess.run(
        ["espeak-ng", "-v", "fr-fr", "-s", "160", "-w", wav, text],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    ensure_mp3(wav, dst)
    os.remove(wav)


def _tts_google(text: str, dst: str) -> None:
    """
    Google Cloud TTS — voix fr-FR-Neural2-C, texte brut (pas de SSML).
    Validé en production avec ADC (gcloud auth application-default login).
    Ne pas spécifier sample_rate_hertz dans AudioConfig : cause INVALID_ARGUMENT
    avec les voix Neural2/Journey.
    Nécessite : pip install google-cloud-texttospeech
    """
    from google.cloud import texttospeech
    client = texttospeech.TextToSpeechClient()
    response = client.synthesize_speech(
        input=texttospeech.SynthesisInput(text=text),
        voice=texttospeech.VoiceSelectionParams(language_code="fr-FR", name="fr-FR-Neural2-C"),
        audio_config=texttospeech.AudioConfig(audio_encoding=texttospeech.AudioEncoding.MP3),
    )
    raw = dst + ".raw.mp3"
    with open(raw, "wb") as f:
        f.write(response.audio_content)
    ensure_mp3(raw, dst)
    os.remove(raw)


def _tts_elevenlabs(text: str, dst: str) -> None:
    """
    ElevenLabs TTS via SDK officiel (elevenlabs.io/docs/eleven-api/quickstart).
    Le SDK peut retourner un bytes ou un générateur selon la version installée ;
    les deux cas sont gérés.
    Nécessite : pip install elevenlabs
    Variables : ELEVENLABS_API_KEY (obligatoire), ELEVENLABS_VOICE_ID (optionnel).
    """
    from elevenlabs.client import ElevenLabs
    api_key = os.environ.get("ELEVENLABS_API_KEY")
    if not api_key:
        raise RuntimeError(
            "ELEVENLABS_API_KEY manquante. Récupérez votre clé sur elevenlabs.io → Profil → API Key."
        )
    voice_id = os.environ.get("ELEVENLABS_VOICE_ID", "JBFqnCBsd6RMkjVDRZzb")
    client = ElevenLabs(api_key=api_key)
    audio = client.text_to_speech.convert(
        voice_id=voice_id,
        text=text,
        model_id="eleven_multilingual_v2",
        language_code="fr",
        output_format="mp3_44100_128",
    )
    raw = dst + ".raw.mp3"
    with open(raw, "wb") as f:
        if isinstance(audio, (bytes, bytearray)):
            f.write(audio)
        else:
            for chunk in audio:
                if chunk:
                    f.write(chunk)
    ensure_mp3(raw, dst)
    os.remove(raw)


_kokoro_pipeline = None


def _tts_kokoro(text: str, dst: str) -> None:
    """
    Kokoro-82M — synthèse locale, licence Apache 2.0.
    Pipeline instancié une seule fois pour toute la session.
    Nécessite : pip install kokoro soundfile torch + apt install espeak-ng
    """
    global _kokoro_pipeline
    import numpy as np
    import soundfile as sf
    if _kokoro_pipeline is None:
        from kokoro import KPipeline
        _kokoro_pipeline = KPipeline(lang_code="f")
    chunks = [audio for _, _, audio in _kokoro_pipeline(text, voice="ff_siwis")]
    if not chunks:
        raise RuntimeError(f"Kokoro n'a produit aucun segment audio pour : {text[:60]!r}")
    full = np.concatenate(chunks) if len(chunks) > 1 else chunks[0]
    wav = dst + ".wav"
    sf.write(wav, full, 24000)
    ensure_mp3(wav, dst)
    os.remove(wav)


# ---------------------------------------------------------------------------
# Thumbnail
# ---------------------------------------------------------------------------

def make_thumbnail(src_path: str | None, titre: str, dst_path: str) -> None:
    """Génère un PNG 320×240. Redimensionne src_path si fourni, sinon génère."""
    from PIL import Image, ImageDraw, ImageFont
    if src_path:
        Image.open(src_path).convert("RGB").resize((320, 240)).save(dst_path, "PNG")
        return
    img = Image.new("RGB", (320, 240), color=(30, 30, 50))
    draw = ImageDraw.Draw(img)
    label = titre[:30]
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 28)
    except OSError:
        font = ImageFont.load_default()
    w = draw.textlength(label, font=font)
    draw.text(((320 - w) / 2, 100), label, font=font, fill=(255, 255, 255))
    img.save(dst_path, "PNG")


# ---------------------------------------------------------------------------
# Construction du story.json
# ---------------------------------------------------------------------------

def build_story_json(
    blocks: dict,
    root_id: str,
    titre: str,
    asset_for_slug: dict,
    image_for_slug: dict,
    cover_image_asset: str,
) -> dict:
    """
    Construit le dict story.json au format Archive STUdio v1.

    Structure source : marian-m12l/studio
        core/.../ArchiveStoryPackWriter.java  — structure JSON
        web-ui/javascript/src/utils/writer.js — logique menus (suffixes UUID)
        web-ui/javascript/src/utils/sample.js — homeTransition null = retour sélection packs

    Suffixes UUID déterministes par bloc :
        111111111111 → questionAction    333333333333 → optionsAction
        222222222222 → questionStage     44444444XXXX → optionStage(i)
        555555555555 → storyAction
    """
    base_uuid = {bid: str(uuid.uuid4()) for bid in blocks}

    def q_action(bid):    return alter_uuid(base_uuid[bid], "111111111111")
    def q_stage(bid):     return alter_uuid(base_uuid[bid], "222222222222")
    def opts_action(bid): return alter_uuid(base_uuid[bid], "333333333333")
    def opt_stage(bid, i):return alter_uuid(base_uuid[bid], "44444444" + str(i).zfill(4))
    def story_action(bid):return alter_uuid(base_uuid[bid], "555555555555")

    def wrap_target(target_bid: str) -> dict:
        tgt = blocks[target_bid]
        if tgt["type"] == "recit":
            return {"actionNode": story_action(target_bid), "optionIndex": 0}
        return {"actionNode": q_action(target_bid), "optionIndex": 0}

    has_menu = any(b["type"] == "carrefour" for b in blocks.values())
    first_useful = wrap_target(root_id)

    stage_nodes, action_nodes = [], []
    cover_uuid = str(uuid.uuid4())

    stage_nodes.append({
        "uuid": cover_uuid, "type": "cover", "groupId": cover_uuid,
        "name": "Couverture", "position": None,
        "image": cover_image_asset,
        "audio": asset_for_slug.get("couverture_titre"),
        "okTransition": first_useful,
        "homeTransition": None,
        "controlSettings": {"wheel": True, "ok": True, "home": False, "pause": False, "autoplay": False},
        "squareOne": True,
    })

    for bid, b in blocks.items():
        if b["type"] == "recit":
            slug = f"recit_{slugify(b['title'])}_{bid[-6:]}"
            has_next = bool(b.get("next"))
            stage_nodes.append({
                "uuid": base_uuid[bid], "type": "story", "groupId": base_uuid[bid],
                "name": b["title"], "position": None,
                "image": image_for_slug.get(slug),
                "audio": asset_for_slug[slug],
                "okTransition": (
                    wrap_target(b["next"]) if has_next
                    else (first_useful if has_menu else None)
                ),
                "homeTransition": first_useful if has_menu else None,
                "controlSettings": {
                    "wheel": False, "ok": False, "home": True, "pause": True, "autoplay": True
                },
            })
            action_nodes.append({
                "id": story_action(bid), "type": "story.storyaction",
                "groupId": base_uuid[bid], "name": b["title"] + ".storyaction",
                "options": [base_uuid[bid]],
            })
        else:
            slug_q = f"question_{slugify(b['title'])}_{bid[-6:]}"
            parent_q_action = q_action(bid)
            stage_nodes.append({
                "uuid": q_stage(bid), "type": "menu.questionstage",
                "groupId": base_uuid[bid],
                "name": b["title"] + ".questionstage",
                "image": image_for_slug.get(slug_q),
                "audio": asset_for_slug[slug_q],
                "okTransition": {"actionNode": opts_action(bid), "optionIndex": 0},
                "homeTransition": {"actionNode": parent_q_action, "optionIndex": 0},
                "controlSettings": {
                    "wheel": False, "ok": False, "home": False, "pause": False, "autoplay": True
                },
            })
            action_nodes.append({
                "id": parent_q_action, "type": "menu.questionaction",
                "groupId": base_uuid[bid], "name": b["title"] + ".questionaction",
                "options": [q_stage(bid)],
            })
            option_uuids = []
            for i, opt in enumerate(b["options"]):
                if not opt.get("targetId"):
                    continue
                slug_o = f"reponse_{slugify(opt['label'])}_{bid[-6:]}"
                osu = opt_stage(bid, i)
                option_uuids.append(osu)
                stage_nodes.append({
                    "uuid": osu, "type": "menu.optionstage",
                    "groupId": base_uuid[bid],
                    "name": opt["label"],
                    "image": image_for_slug.get(slug_o),
                    "audio": asset_for_slug[slug_o],
                    "okTransition": wrap_target(opt["targetId"]),
                    "homeTransition": {"actionNode": parent_q_action, "optionIndex": 0},
                    "controlSettings": {
                        "wheel": True, "ok": True, "home": True, "pause": False, "autoplay": False
                    },
                })
            action_nodes.append({
                "id": opts_action(bid), "type": "menu.optionsaction",
                "groupId": base_uuid[bid], "name": b["title"] + ".optionsaction",
                "options": option_uuids,
            })

    stage_nodes.sort(key=lambda n: 0 if n.get("squareOne") else 1)
    return {
        "format": "v1",
        "title": titre,
        "description": "Pack généré par build_pack.py",
        "version": 1,
        "nightModeAvailable": False,
        "stageNodes": stage_nodes,
        "actionNodes": action_nodes,
    }


# ---------------------------------------------------------------------------
# Commande : kit
# ---------------------------------------------------------------------------

def cmd_kit(args) -> None:
    blocks, _ = load_arborescence(args.arborescence)
    audios = needed_audios(blocks, args.titre)
    audio_dir = os.path.join(args.dossier, "audio")
    os.makedirs(audio_dir, exist_ok=True)
    os.makedirs(os.path.join(args.dossier, "images"), exist_ok=True)

    for slug, (text, desc) in audios.items():
        with open(os.path.join(audio_dir, slug + ".txt"), "w", encoding="utf-8") as f:
            f.write(f"# {desc}\n# Sauvegardez l'enregistrement sous : {slug}.mp3\n\n{text}\n")

    readme = os.path.join(args.dossier, "LISEZMOI.txt")
    with open(readme, "w", encoding="utf-8") as f:
        f.write(
            f"{len(audios)} fichiers audio à produire.\n\n"
            "Pour chaque .txt dans audio/ :\n"
            "  1. Enregistrez le texte.\n"
            "  2. Sauvegardez au même nom, extension .mp3 (ou .wav .m4a .ogg .flac).\n\n"
            "Pictogrammes (facultatif) : déposez des images dans images/,\n"
            "même nom que le .mp3 correspondant.\n\n"
            f"Ensuite : python3 build_pack.py build {args.arborescence} {args.dossier} mon-pack.zip\n"
        )
    print(f"Kit : {len(audios)} passages → {audio_dir}/")


# ---------------------------------------------------------------------------
# Commande : build
# ---------------------------------------------------------------------------

def cmd_build(args) -> None:
    blocks, root_id = load_arborescence(args.arborescence)
    titre = args.titre or "Mon histoire"
    audios = needed_audios(blocks, titre)

    work = os.path.join(args.dossier, "_build_tmp")
    if os.path.exists(work):
        shutil.rmtree(work)
    os.makedirs(os.path.join(work, "assets"))

    audio_dir = os.path.join(args.dossier, "audio")
    images_dir = os.path.join(args.dossier, "images")
    lisible_dir = os.path.join(args.dossier, "audio_lisible")
    os.makedirs(lisible_dir, exist_ok=True)

    asset_for_slug: dict = {}
    image_for_slug: dict = {}
    missing: list = []

    for slug, (text, desc) in audios.items():
        src = None
        for ext in (".mp3", ".wav", ".m4a", ".ogg", ".flac"):
            candidate = os.path.join(audio_dir, slug + ext)
            if os.path.exists(candidate):
                src = candidate
                break

        out = os.path.join(work, f"tmp_{slug}.mp3")
        if src:
            ensure_mp3(src, out)
        elif args.tts:
            ptype = "story" if slug.startswith("recit_") else "question" if slug.startswith("question_") else "option"
            tts_dispatch(text, out, engine=args.tts, passage_type=ptype)
        else:
            missing.append(slug)
            continue

        data = open(out, "rb").read()
        sha1 = hashlib.sha1(data).hexdigest()
        fname = sha1 + ".mp3"
        shutil.copy(out, os.path.join(work, "assets", fname))
        shutil.copy(out, os.path.join(lisible_dir, slug + ".mp3"))
        os.remove(out)
        asset_for_slug[slug] = fname

        for ext in (".png", ".jpg", ".jpeg"):
            img_src = os.path.join(images_dir, slug + ext)
            if os.path.exists(img_src):
                out_png = os.path.join(work, f"tmp_{slug}.png")
                ensure_image(img_src, out_png)
                idata = open(out_png, "rb").read()
                ifname = hashlib.sha1(idata).hexdigest() + ".png"
                shutil.copy(out_png, os.path.join(work, "assets", ifname))
                os.remove(out_png)
                image_for_slug[slug] = ifname
                break

    if missing:
        print(f"{len(missing)} audio(s) manquant(s) (ajoutez --tts pour synthèse automatique) :")
        for m in missing:
            print(f"  - {m}.mp3")
        sys.exit(1)

    # Thumbnail
    thumb_path = os.path.join(work, "thumbnail.png")
    user_thumb = os.path.join(args.dossier, "thumbnail.png")
    make_thumbnail(user_thumb if os.path.exists(user_thumb) else None, titre, thumb_path)

    thumb_data = open(thumb_path, "rb").read()
    cover_image_asset = hashlib.sha1(thumb_data).hexdigest() + ".png"
    shutil.copy(thumb_path, os.path.join(work, "assets", cover_image_asset))

    # story.json
    story = build_story_json(blocks, root_id, titre, asset_for_slug, image_for_slug, cover_image_asset)
    story_path = os.path.join(work, "story.json")
    with open(story_path, "w", encoding="utf-8") as f:
        json.dump(story, f, ensure_ascii=False, indent=2)

    # ZIP
    os.makedirs(os.path.dirname(os.path.abspath(args.sortie)), exist_ok=True)
    if os.path.exists(args.sortie):
        os.remove(args.sortie)
    with zipfile.ZipFile(args.sortie, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(story_path, "story.json")
        zf.write(thumb_path, "thumbnail.png")
        for fname in os.listdir(os.path.join(work, "assets")):
            zf.write(os.path.join(work, "assets", fname), f"assets/{fname}")

    # Correspondances
    corr_path = os.path.join(args.dossier, "correspondances.txt")
    with open(corr_path, "w", encoding="utf-8") as f:
        f.write("Correspondances nom lisible → SHA1 dans le zip\n")
        f.write("=" * 60 + "\n\n")
        for slug, fname in sorted(asset_for_slug.items()):
            _, desc = audios[slug]
            f.write(f"{slug}.mp3\n  {desc}\n  assets/{fname}\n\n")

    shutil.rmtree(work)
    print(f"Pack : {args.sortie}  ({len(story['stageNodes'])} scènes)")
    print(f"  Lisibles  : {lisible_dir}/")
    print(f"  Correspondances : {corr_path}")


# ---------------------------------------------------------------------------
# Commande : script
# ---------------------------------------------------------------------------

def narrative_order(blocks: dict, root_id: str) -> list:
    order, seen = [], set()

    def visit(bid):
        if bid in seen or bid not in blocks:
            return
        seen.add(bid)
        order.append(bid)
        b = blocks[bid]
        if b["type"] == "carrefour":
            for opt in b["options"]:
                if opt.get("targetId"):
                    visit(opt["targetId"])
        elif b.get("next"):
            visit(b["next"])

    visit(root_id)
    for bid in blocks:
        visit(bid)
    return order


def cmd_script(args) -> None:
    blocks, root_id = load_arborescence(args.arborescence)
    order = narrative_order(blocks, root_id)
    lines = [
        "FEUILLE DE LECTURE — enregistrement d'une traite avec Audacity",
        "=" * 70,
        "",
        "Avant chaque texte : Ctrl+B (ou Cmd+B), tapez EXACTEMENT l'étiquette indiquée,",
        "validez (Entrée), puis lisez le texte à voix haute.",
        "",
        "=" * 70,
        "",
        "--- ÉTIQUETTE : couverture_titre ---",
        f"[Titre du pack]",
        "",
        args.titre,
        "",
        "",
    ]
    written: set = set()
    for bid in order:
        b = blocks[bid]
        if b["type"] == "recit":
            slug = f"recit_{slugify(b['title'])}_{bid[-6:]}"
            if slug in written:
                continue
            written.add(slug)
            lines += [f"--- ÉTIQUETTE : {slug} ---", f"[Récit : {b['title']}]", "", b["text"], "", ""]
        else:
            suffix = bid[-6:]
            slug_q = f"question_{slugify(b['title'])}_{suffix}"
            if slug_q not in written:
                written.add(slug_q)
                question = b.get("question") or b["title"]
                lines += [f"--- ÉTIQUETTE : {slug_q} ---", f"[Question : {b['title']}]", "", question, "", ""]
            for opt in b["options"]:
                if not opt.get("targetId"):
                    continue
                slug_o = f"reponse_{slugify(opt['label'])}_{suffix}"
                if slug_o in written:
                    continue
                written.add(slug_o)
                lines += [f"--- ÉTIQUETTE : {slug_o} ---", f"[Réponse : {opt['label']}]", "", opt["label"], "", ""]

    with open(args.sortie, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"Feuille : {args.sortie}  ({len(written)} passages)")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Génère un pack Lunii/STUdio depuis l'arborescence à histoires."
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_kit = sub.add_parser("kit", help="Génère les fichiers texte des audios à produire.")
    p_kit.add_argument("arborescence")
    p_kit.add_argument("dossier")
    p_kit.add_argument("--titre", default="Mon histoire")
    p_kit.set_defaults(func=cmd_kit)

    p_build = sub.add_parser("build", help="Assemble le pack ZIP final.")
    p_build.add_argument("arborescence")
    p_build.add_argument("dossier")
    p_build.add_argument("sortie")
    p_build.add_argument(
        "--tts",
        choices=["espeak", "kokoro", "google", "elevenlabs"],
        default=None,
        help=(
            "Synthèse vocale automatique pour les audios manquants. "
            "espeak : robotique, hors-ligne. "
            "kokoro : local, qualité correcte (pip install kokoro soundfile torch). "
            "google : Neural2-C, validé en production (pip install google-cloud-texttospeech + ADC). "
            "elevenlabs : expressif, payant (pip install elevenlabs + ELEVENLABS_API_KEY)."
        ),
    )
    p_build.add_argument("--titre", default=None)
    p_build.set_defaults(func=cmd_build)

    p_script = sub.add_parser("script", help="Génère une feuille de lecture continue (Audacity).")
    p_script.add_argument("arborescence")
    p_script.add_argument("sortie")
    p_script.add_argument("--titre", default="Mon histoire")
    p_script.set_defaults(func=cmd_script)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
