#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_pack.py — Convertit un fichier exporté par l'arborescence à histoires
en pack "Archive" natif STUdio (Lunii), avec audio et pictogrammes.

Usage :
    1) Générer le kit d'enregistrement (liste des audios à produire) :
       python3 build_pack.py kit arborescence.json dossier_travail/

    2) Après avoir déposé vos MP3 (et éventuellement des PNG/JPG) dans
       dossier_travail/audio/ et dossier_travail/images/ :
       python3 build_pack.py build arborescence.json dossier_travail/ pack-final.zip

    Option --tts : pour les audios manquants, génère une voix de synthèse
    de secours (espeak-ng, à installer : sudo apt install espeak-ng ffmpeg)
    au lieu de bloquer avec une erreur.
"""
import json, os, re, sys, hashlib, shutil, subprocess, uuid, argparse, unicodedata

# ---------- utilitaires ----------

def slugify(text):
    text = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode('ascii')
    text = re.sub(r'[^a-zA-Z0-9]+', '-', text).strip('-').lower()
    return text[:80] or 'sans-titre'

def alter_uuid(u, suffix):
    return u[:-len(suffix)] + suffix

def load_arborescence(path):
    with open(path, encoding='utf-8') as f:
        data = json.load(f)
    blocks = data['blocks']
    all_ids = set(blocks)
    referenced = set()
    for b in blocks.values():
        if b['type'] == 'carrefour':
            referenced.update(o['targetId'] for o in b['options'] if o.get('targetId'))
        elif b.get('next'):
            referenced.add(b['next'])
    roots = [i for i in all_ids if i not in referenced]
    if len(roots) != 1:
        print(f"ATTENTION : {len(roots)} point(s) de départ détecté(s) (il en faut un seul).")
        print("Vérifiez votre arborescence dans l'outil avant de continuer.")
        sys.exit(1)
    return blocks, roots[0]

# ---------- inventaire des audios nécessaires ----------

def needed_audios(blocks, titre='Mon histoire'):
    """Retourne une liste de (slug, texte_a_dire, description) pour chaque audio requis."""
    items = []
    items.append(('couverture_titre', titre, "Titre du pack (écran d'accueil de la Lunii)"))
    for bid, b in blocks.items():
        if b['type'] == 'recit':
            items.append((f"recit_{slugify(b['title'])}_{bid[-6:]}", b['text'],
                           f"Récit : {b['title']}"))
        else:
            question = b.get('question') or b['title']
            items.append((f"question_{slugify(b['title'])}_{bid[-6:]}", question,
                           f"Question du carrefour : {b['title']}"))
            for opt in b['options']:
                if opt.get('targetId'):
                    items.append((f"reponse_{slugify(opt['label'])}", opt['label'],
                                   f"Réponse : {opt['label']}"))
    # dédoublonner par slug (une réponse "Mélisande" ne s'enregistre qu'une fois)
    seen = {}
    for slug, text, desc in items:
        seen.setdefault(slug, (text, desc))
    return seen  # dict slug -> (texte, description)

def cmd_kit(args):
    blocks, root = load_arborescence(args.arborescence)
    audios = needed_audios(blocks, args.titre)
    out_audio = os.path.join(args.dossier, 'audio')
    out_images = os.path.join(args.dossier, 'images')
    os.makedirs(out_audio, exist_ok=True)
    os.makedirs(out_images, exist_ok=True)

    for slug, (text, desc) in audios.items():
        txt_path = os.path.join(out_audio, slug + '.txt')
        with open(txt_path, 'w', encoding='utf-8') as f:
            f.write(f"# {desc}\n# Enregistrez ce texte, puis sauvegardez le résultat sous :\n")
            f.write(f"# {slug}.mp3  (dans ce même dossier)\n\n")
            f.write(text + "\n")

    readme = os.path.join(args.dossier, 'LISEZMOI.txt')
    with open(readme, 'w', encoding='utf-8') as f:
        f.write(f"{len(audios)} fichiers audio à produire.\n\n"
                "Pour chaque .txt dans le dossier audio/ :\n"
                "  1. Lisez le texte (ou faites-le lire) et enregistrez-le.\n"
                "  2. Sauvegardez l'enregistrement au même nom que le .txt, mais en .mp3\n"
                "     (ex : recit_bono_abc123.txt -> recit_bono_abc123.mp3), dans le même dossier.\n"
                "  3. Vous pouvez alors supprimer le .txt, ou le laisser (il sera ignoré).\n\n"
                "Pictogrammes (facultatif) : déposez des images 320x240 (PNG ou JPG) dans le\n"
                "dossier images/, avec le même nom que le .mp3 correspondant.\n"
                "Si aucune image n'est fournie pour un bloc, il n'aura simplement pas d'image.\n\n"
                "Une fois prêt, lancez :\n"
                f"  python3 build_pack.py build {args.arborescence} {args.dossier} mon-pack.zip\n")

    print(f"Kit généré dans {args.dossier}/")
    print(f"  -> {len(audios)} textes à enregistrer dans audio/*.txt")
    print(f"  -> Notice complète : {readme}")

# ---------- construction du pack ----------

def ensure_mp3(src_path, dst_path):
    """Convertit n'importe quel format audio vers le format attendu (44100Hz mono mp3)."""
    subprocess.run(['ffmpeg', '-y', '-loglevel', 'error', '-i', src_path,
                     '-ar', '44100', '-ac', '1', '-codec:a', 'libmp3lame', '-qscale:a', '4',
                     dst_path], check=True)

def ensure_image(src_path, dst_path):
    """Redimensionne/convertit vers 320x240 PNG."""
    from PIL import Image
    img = Image.open(src_path).convert('RGB')
    img = img.resize((320, 240))
    img.save(dst_path, format='PNG')

def tts_fallback(text, dst_path, engine='espeak', passage_type='story'):
    if engine == 'kokoro':
        kokoro_tts(text, dst_path)
        return
    if engine == 'google':
        google_tts(text, dst_path, passage_type=passage_type)
        return
    if engine == 'elevenlabs':
        elevenlabs_tts(text, dst_path)
        return
    wav = dst_path + '.wav'
    subprocess.run(['espeak-ng', '-v', 'fr-fr', '-s', '160', '-w', wav, text], check=True,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    ensure_mp3(wav, dst_path)
    os.remove(wav)

def elevenlabs_tts(text, dst_path):
    """
    ElevenLabs Text-to-Speech (voix très expressive, payante après un petit
    palier gratuit). NON TESTÉ ici (elevenlabs.io hors de portée de mon
    réseau) — code écrit d'après la documentation officielle du SDK Python
    actuel (client.text_to_speech.convert, pas l'ancienne API generate()/play()
    qu'on trouve encore dans certains exemples obsolètes).

    Nécessite : pip install elevenlabs
    Configuration (variables d'environnement) :
      ELEVENLABS_API_KEY   (obligatoire)
      ELEVENLABS_VOICE_ID  (optionnel, sinon voix par défaut ci-dessous)
    """
    from elevenlabs.client import ElevenLabs

    api_key = os.environ.get('ELEVENLABS_API_KEY')
    if not api_key:
        raise RuntimeError(
            "Variable d'environnement ELEVENLABS_API_KEY manquante. "
            "Récupérez votre clé sur elevenlabs.io -> Profil -> API Key."
        )
    voice_id = os.environ.get('ELEVENLABS_VOICE_ID', 'JBFqnCBsd6RMkjVDRZzb')

    client = ElevenLabs(api_key=api_key)
    audio = client.text_to_speech.convert(
        voice_id=voice_id,
        text=text,
        model_id='eleven_multilingual_v2',
        language_code='fr',
        output_format='mp3_44100_128',
    )
    raw_mp3 = dst_path + '.raw.mp3'
    with open(raw_mp3, 'wb') as f:
        # La doc officielle (elevenlabs.io/docs/eleven-api/quickstart) ne précise pas
        # si .convert() renvoie un bloc bytes unique ou un générateur de morceaux —
        # elle passe juste le résultat à play() sans jamais l'inspecter. On gère les
        # deux cas plutôt que de supposer l'un ou l'autre.
        if isinstance(audio, (bytes, bytearray)):
            f.write(audio)
        else:
            for chunk in audio:
                if chunk:
                    f.write(chunk)
    # Renormalisation (mono/44100Hz garantis) par cohérence avec les autres moteurs
    ensure_mp3(raw_mp3, dst_path)
    os.remove(raw_mp3)

def google_tts(text, dst_path, passage_type='story'):
    """
    Google Cloud Text-to-Speech — version minimale validée.
    Voix : fr-FR-Neural2-C (qualité Neural2, français, sans restrictions SSML).
    Texte brut uniquement : pas de SSML pour éviter tout INVALID_ARGUMENT.
    Nécessite : pip install google-cloud-texttospeech
    Authentification : ADC (gcloud auth application-default login)
    """
    from google.cloud import texttospeech

    client = texttospeech.TextToSpeechClient()
    synthesis_input = texttospeech.SynthesisInput(text=text)
    voice = texttospeech.VoiceSelectionParams(
        language_code="fr-FR",
        name="fr-FR-Neural2-C",
    )
    audio_config = texttospeech.AudioConfig(
        audio_encoding=texttospeech.AudioEncoding.MP3,
    )
    response = client.synthesize_speech(
        input=synthesis_input, voice=voice, audio_config=audio_config
    )
    with open(dst_path, 'wb') as f:
        f.write(response.audio_content)

_kokoro_pipeline = None

def kokoro_tts(text, dst_path):
    """
    Synthèse vocale française de bien meilleure qualité qu'espeak-ng, entièrement locale.
    Nécessite : pip install kokoro soundfile torch  +  apt install espeak-ng
    (espeak-ng reste utilisé par Kokoro en interne pour la phonétisation, pas pour la voix finale)
    Le modèle (~327 Mo) se télécharge automatiquement au premier lancement, puis fonctionne hors ligne.
    """
    global _kokoro_pipeline
    import soundfile as sf
    if _kokoro_pipeline is None:
        from kokoro import KPipeline
        _kokoro_pipeline = KPipeline(lang_code='f')  # 'f' = français
    wav = dst_path + '.wav'
    # Kokoro renvoie un générateur de segments (texte découpé automatiquement) ; on les concatène
    import numpy as np
    chunks = []
    for _, _, audio in _kokoro_pipeline(text, voice='ff_siwis'):
        chunks.append(audio)
    full_audio = np.concatenate(chunks) if len(chunks) > 1 else chunks[0]
    sf.write(wav, full_audio, 24000)
    ensure_mp3(wav, dst_path)
    os.remove(wav)

def cmd_build(args):
    blocks, root_id = load_arborescence(args.arborescence)
    titre = args.titre or 'Mon histoire'
    audios = needed_audios(blocks, titre)

    work = os.path.join(args.dossier, '_build_tmp')
    if os.path.exists(work): shutil.rmtree(work)
    os.makedirs(f'{work}/assets')

    audio_dir = os.path.join(args.dossier, 'audio')
    images_dir = os.path.join(args.dossier, 'images')

    # Dossier avec les MP3 nommés de façon lisible (pour usage manuel si besoin)
    lisible_dir = os.path.join(args.dossier, 'audio_lisible')
    os.makedirs(lisible_dir, exist_ok=True)

    asset_for_slug = {}
    image_for_slug = {}
    missing = []

    for slug, (text, desc) in audios.items():
        mp3_src = None
        for ext in ('.mp3', '.wav', '.m4a', '.ogg', '.flac'):
            candidate = os.path.join(audio_dir, slug + ext)
            if os.path.exists(candidate):
                mp3_src = candidate
                break
        out_mp3 = f'{work}/tmp_{slug}.mp3'
        if mp3_src:
            ensure_mp3(mp3_src, out_mp3)
        elif args.tts:
            if slug.startswith('recit_'):
                ptype = 'story'
            elif slug.startswith('question_'):
                ptype = 'question'
            else:
                ptype = 'option'
            tts_fallback(text, out_mp3, engine=args.tts, passage_type=ptype)
        else:
            missing.append(slug)
            continue
        with open(out_mp3, 'rb') as f: data = f.read()
        sha1 = hashlib.sha1(data).hexdigest()
        fname = f'{sha1}.mp3'
        shutil.copy(out_mp3, f'{work}/assets/{fname}')
        # Copie lisible avec le slug comme nom
        shutil.copy(out_mp3, os.path.join(lisible_dir, slug + '.mp3'))
        os.remove(out_mp3)
        asset_for_slug[slug] = fname

        img_src = None
        for ext in ('.png', '.jpg', '.jpeg'):
            p = os.path.join(images_dir, slug + ext)
            if os.path.exists(p):
                img_src = p; break
        if img_src:
            out_png = f'{work}/tmp_{slug}.png'
            ensure_image(img_src, out_png)
            with open(out_png, 'rb') as f: idata = f.read()
            isha1 = hashlib.sha1(idata).hexdigest()
            ifname = f'{isha1}.png'
            shutil.copy(out_png, f'{work}/assets/{ifname}')
            os.remove(out_png)
            image_for_slug[slug] = ifname

    if missing:
        print(f"{len(missing)} audio(s) manquant(s) (relancez avec --tts pour une voix de secours) :")
        for m in missing: print("  -", m + '.mp3')
        sys.exit(1)

    # Générer thumbnail.png (320x240) — requis pour que le pack apparaisse
    # dans la liste des packs de la Lunii. Généré AVANT story.json car le
    # nœud "cover" a besoin de le référencer comme asset.
    thumbnail_path = f'{work}/thumbnail.png'
    user_thumbnail = os.path.join(args.dossier, 'thumbnail.png')
    if os.path.exists(user_thumbnail):
        from PIL import Image as PILImage
        img = PILImage.open(user_thumbnail).convert('RGB').resize((320, 240))
        img.save(thumbnail_path, 'PNG')
    else:
        try:
            from PIL import Image as PILImage, ImageDraw, ImageFont
            img = PILImage.new('RGB', (320, 240), color=(30, 30, 50))
            draw = ImageDraw.Draw(img)
            title_short = titre[:30]
            try:
                font = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', 28)
            except Exception:
                font = ImageFont.load_default()
            w = draw.textlength(title_short, font=font)
            draw.text(((320 - w) / 2, 100), title_short, font=font, fill=(255, 255, 255))
            img.save(thumbnail_path, 'PNG')
        except Exception:
            import struct, zlib
            def png_chunk(name, data):
                c = zlib.crc32(name + data) & 0xffffffff
                return struct.pack('>I', len(data)) + name + data + struct.pack('>I', c)
            w, h = 320, 240
            raw = b''.join(b'\x00' + b'\xff' * (w * 3) for _ in range(h))
            idat = zlib.compress(raw)
            png = (b'\x89PNG\r\n\x1a\n'
                   + png_chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0))
                   + png_chunk(b'IDAT', idat)
                   + png_chunk(b'IEND', b''))
            with open(thumbnail_path, 'wb') as tf: tf.write(png)

    # Copie du thumbnail dans assets/ (sous son propre hash) pour que le
    # nœud cover puisse le référencer comme image.
    with open(thumbnail_path, 'rb') as f: _thumb_data = f.read()
    _thumb_sha1 = hashlib.sha1(_thumb_data).hexdigest()
    cover_image_asset = f'{_thumb_sha1}.png'
    shutil.copy(thumbnail_path, f'{work}/assets/{cover_image_asset}')

    # ---- construction de story.json (structure Cover/Story/Menu de STUdio) ----
    base_uuid = {bid: str(uuid.uuid4()) for bid in blocks}
    def q_action(bid):    return alter_uuid(base_uuid[bid], "111111111111")
    def q_stage(bid):     return alter_uuid(base_uuid[bid], "222222222222")
    def opts_action(bid): return alter_uuid(base_uuid[bid], "333333333333")
    def opt_stage(bid,i): return alter_uuid(base_uuid[bid], "44444444"+str(i).zfill(4))
    def story_action(bid):return alter_uuid(base_uuid[bid], "555555555555")

    def wrap_target(target_bid):
        tgt = blocks[target_bid]
        if tgt['type'] == 'recit':
            return {"actionNode": story_action(target_bid), "optionIndex": 0}
        return {"actionNode": q_action(target_bid), "optionIndex": 0}

    first_useful = wrap_target(root_id)
    stage_nodes, action_nodes = [], []

    # Nœud "cover" : l'écran d'accueil du pack, distinct du carrefour racine.
    # C'est LUI le vrai squareOne — sans lui, la Lunii ne présente pas
    # correctement le pack dans son menu de sélection.
    cover_uuid = str(uuid.uuid4())
    stage_nodes.append({
        "uuid": cover_uuid, "type": "cover", "groupId": cover_uuid,
        "name": "Couverture", "position": None,
        "image": cover_image_asset,
        "audio": asset_for_slug.get('couverture_titre'),
        "okTransition": first_useful,
        "homeTransition": None,
        "controlSettings": {"wheel": True, "ok": True, "home": False, "pause": False, "autoplay": False},
        "squareOne": True
    })

    for bid, b in blocks.items():
        if b['type'] == 'recit':
            slug = f"recit_{slugify(b['title'])}_{bid[-6:]}"
            stage_nodes.append({
                "uuid": base_uuid[bid], "type": "story", "groupId": base_uuid[bid],
                "name": b['title'], "position": None,
                "image": image_for_slug.get(slug), "audio": asset_for_slug[slug],
                "okTransition": wrap_target(b['next']) if b.get('next') else first_useful,
                "homeTransition": first_useful,
                "controlSettings": {"wheel": False, "ok": False, "home": True, "pause": True, "autoplay": True},
            })
            action_nodes.append({"id": story_action(bid), "type": "story.storyaction",
                                  "groupId": base_uuid[bid], "name": b['title']+".storyaction",
                                  "options": [base_uuid[bid]]})
        else:
            slug_q = f"question_{slugify(b['title'])}_{bid[-6:]}"
            stage_nodes.append({
                "uuid": q_stage(bid), "type": "menu.questionstage", "groupId": base_uuid[bid],
                "name": b['title']+".questionstage", "image": image_for_slug.get(slug_q),
                "audio": asset_for_slug[slug_q],
                "okTransition": {"actionNode": opts_action(bid), "optionIndex": 0},
                "homeTransition": None,
                "controlSettings": {"wheel": False, "ok": False, "home": False, "pause": False, "autoplay": True},
            })
            action_nodes.append({"id": q_action(bid), "type": "menu.questionaction",
                                  "groupId": base_uuid[bid], "name": b['title']+".questionaction",
                                  "options": [q_stage(bid)]})
            option_uuids = []
            for i, opt in enumerate(b['options']):
                if not opt.get('targetId'): continue
                slug_o = f"reponse_{slugify(opt['label'])}"
                osu = opt_stage(bid, i)
                option_uuids.append(osu)
                stage_nodes.append({
                    "uuid": osu, "type": "menu.optionstage", "groupId": base_uuid[bid],
                    "name": opt['label'], "image": image_for_slug.get(slug_o),
                    "audio": asset_for_slug[slug_o],
                    "okTransition": wrap_target(opt['targetId']), "homeTransition": None,
                    "controlSettings": {"wheel": True, "ok": True, "home": True, "pause": False, "autoplay": False}
                })
            action_nodes.append({"id": opts_action(bid), "type": "menu.optionsaction",
                                  "groupId": base_uuid[bid], "name": b['title']+".optionsaction",
                                  "options": option_uuids})

    stage_nodes.sort(key=lambda n: 0 if n.get('squareOne') else 1)
    story = {"format": "v1", "title": titre,
             "description": "Pack genere par build_pack.py",
             "version": 1, "nightModeAvailable": False,
             "stageNodes": stage_nodes, "actionNodes": action_nodes}
    with open(f'{work}/story.json', 'w', encoding='utf-8') as f:
        json.dump(story, f, ensure_ascii=False, indent=2)

    if os.path.exists(args.sortie): os.remove(args.sortie)
    import zipfile
    with zipfile.ZipFile(args.sortie, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.write(f'{work}/story.json', 'story.json')
        zf.write(thumbnail_path, 'thumbnail.png')
        for fname in os.listdir(f'{work}/assets'):
            zf.write(f'{work}/assets/{fname}', f'assets/{fname}')

    # Fichier de correspondances lisible → SHA1
    correspondances_path = os.path.join(args.dossier, 'correspondances.txt')
    with open(correspondances_path, 'w', encoding='utf-8') as f:
        f.write("Correspondances nom lisible → nom SHA1 dans le zip\n")
        f.write("=" * 60 + "\n\n")
        for slug, fname in sorted(asset_for_slug.items()):
            _, (text, desc) = next((k, v) for k, v in needed_audios(blocks, titre).items() if k == slug)
            f.write(f"{slug}.mp3\n")
            f.write(f"  Description : {desc}\n")
            f.write(f"  Dans le zip : assets/{fname}\n\n")

    shutil.rmtree(work)
    print(f"Pack créé : {args.sortie}")
    print(f"  {len(stage_nodes)} scènes, {len(action_nodes)} actions")
    print(f"  MP3 lisibles : {os.path.join(args.dossier, 'audio_lisible/')}")
    print(f"  Correspondances : {correspondances_path}")

# ---------- feuille de lecture continue ----------

def narrative_order(blocks, root_id):
    """Parcourt l'arborescence depuis le départ, dans l'ordre naturel de lecture."""
    order = []
    seen = set()
    def visit(bid):
        if bid in seen or bid not in blocks: return
        seen.add(bid)
        order.append(bid)
        b = blocks[bid]
        if b['type'] == 'carrefour':
            for opt in b['options']:
                if opt.get('targetId'):
                    visit(opt['targetId'])
        elif b.get('next'):
            visit(b['next'])
    visit(root_id)
    for bid in blocks:
        if bid not in seen:
            visit(bid)
    return order

def cmd_script(args):
    blocks, root = load_arborescence(args.arborescence)
    order = narrative_order(blocks, root)

    lines = []
    lines.append("FEUILLE DE LECTURE — à enregistrer d'une traite avec Audacity")
    lines.append("=" * 70)
    lines.append("")
    lines.append("Pour chaque section ci-dessous : avant de lire le texte, ajoutez une")
    lines.append("étiquette Audacity (Ctrl+B ou Cmd+B) et tapez EXACTEMENT le nom indiqué")
    lines.append("(sans le lire à voix haute, bien sûr). Puis lisez le texte normalement.")
    lines.append("")
    lines.append("=" * 70)
    lines.append("")

    lines.append("--- ÉTIQUETTE : couverture_titre ---")
    lines.append("[Titre du pack, annoncé à l'écran d'accueil de la Lunii]")
    lines.append("")
    lines.append(args.titre)
    lines.append("")
    lines.append("")

    written_slugs = set()
    for bid in order:
        b = blocks[bid]
        if b['type'] == 'recit':
            slug = f"recit_{slugify(b['title'])}_{bid[-6:]}"
            if slug in written_slugs: continue
            written_slugs.add(slug)
            lines.append(f"--- ÉTIQUETTE : {slug} ---")
            lines.append(f"[Récit : {b['title']}]")
            lines.append("")
            lines.append(b['text'])
            lines.append("")
            lines.append("")
        else:
            slug_q = f"question_{slugify(b['title'])}_{bid[-6:]}"
            if slug_q not in written_slugs:
                written_slugs.add(slug_q)
                question = b.get('question') or b['title']
                lines.append(f"--- ÉTIQUETTE : {slug_q} ---")
                lines.append(f"[Question du carrefour : {b['title']}]")
                lines.append("")
                lines.append(question)
                lines.append("")
                lines.append("")
            for opt in b['options']:
                if not opt.get('targetId'): continue
                slug_o = f"reponse_{slugify(opt['label'])}"
                if slug_o in written_slugs: continue
                written_slugs.add(slug_o)
                lines.append(f"--- ÉTIQUETTE : {slug_o} ---")
                lines.append(f"[Réponse possible : {opt['label']}]")
                lines.append("")
                lines.append(opt['label'])
                lines.append("")
                lines.append("")

    with open(args.sortie, 'w', encoding='utf-8') as f:
        f.write("\n".join(lines))
    print(f"Feuille de lecture générée : {args.sortie}")
    print(f"  {len(written_slugs)} passages, dans l'ordre de l'histoire.")

# ---------- CLI ----------

parser = argparse.ArgumentParser(description="Génère un pack Lunii/STUdio depuis l'arborescence à histoires")
sub = parser.add_subparsers(dest='cmd', required=True)

p_kit = sub.add_parser('kit', help="Génère la liste des audios à enregistrer")
p_kit.add_argument('arborescence')
p_kit.add_argument('dossier')
p_kit.add_argument('--titre', default='Mon histoire')
p_kit.set_defaults(func=cmd_kit)

p_build = sub.add_parser('build', help="Construit le pack final")
p_build.add_argument('arborescence')
p_build.add_argument('dossier')
p_build.add_argument('sortie')
p_build.add_argument('--tts', choices=['espeak', 'kokoro', 'google', 'elevenlabs'], default=None,
                      help="Génère automatiquement les audios manquants : "
                           "'espeak' (robotique, rapide), "
                           "'kokoro' (local, gratuit, nécessite pip install kokoro soundfile torch), "
                           "'google' (Google Cloud TTS, bonne qualité, nécessite un compte + clé), "
                           "'elevenlabs' (très expressif, payant après un petit palier gratuit, "
                           "nécessite pip install elevenlabs + variable ELEVENLABS_API_KEY)")
p_build.add_argument('--titre', default=None)
p_build.set_defaults(func=cmd_build)

p_script = sub.add_parser('script', help="Génère une feuille de lecture unique, pour enregistrer d'une traite")
p_script.add_argument('arborescence')
p_script.add_argument('sortie')
p_script.add_argument('--titre', default='Mon histoire')
p_script.set_defaults(func=cmd_script)

if __name__ == '__main__':
    args = parser.parse_args()
    args.func(args)
