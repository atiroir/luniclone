# Contexte du projet — Boîte à histoires Lunii

Ce fichier résume ce qui a déjà été établi dans une conversation précédente avec
Claude (sur claude.ai), pour que tu (Claude Code) n'aies pas à tout redécouvrir.

## Le projet

Une famille construit des histoires interactives pour enfants (héros, personnages,
lieux, objets définis dans des fiches JSON), organisées en arborescence (récits
linéaires + carrefours à choix multiples), pour les faire jouer sur un appareil
Lunii (boîte à histoires physique pour enfants).

## Les outils déjà construits

- **`atelier-histoires.html`** et **`arborescence-histoires.html`** : deux pages
  HTML autonomes (aucune dépendance serveur) où la famille crée les fiches de
  personnages/lieux/objets, puis écrit et branche les histoires. Exportent des
  fichiers `.json`.
- **`build_pack.py`** : convertit un export de l'arborescence en pack "Archive"
  natif STUdio (le logiciel officieux qui transfère sur la Lunii). Trois
  commandes : `kit` (génère la liste des audios à enregistrer), `build`
  (assemble le pack final), `script` (feuille de lecture continue pour
  enregistrement à la voix avec Audacity et étiquettes).
- **`pi_pipeline.py`** : orchestration complète pour Raspberry Pi (GitHub → audio
  Google Cloud TTS → pack → Google Drive via rclone). Écrit mais **non testé de
  bout en bout** (réseau restreint côté Claude.ai au moment de l'écriture).

## Le point technique le plus important à ne pas redécouvrir

**Ne pas utiliser `studio-pack-generator`** (outil tiers) : il dépend de `jsr.io`,
souvent inaccessible selon l'environnement réseau. La bonne approche est de
construire directement le format "Archive" natif de STUdio, documenté dans le
code source du dépôt `github.com/marian-m12l/studio` :

- `core/src/main/java/studio/core/v1/writer/archive/ArchiveStoryPackWriter.java`
  → structure exacte de `story.json` (stageNodes / actionNodes).
- `web-ui/javascript/src/utils/writer.js` → logique précise des nœuds "menu"
  simplifiés : **1 questionStage + N optionStages**, chacun avec son propre
  audio nommé (le nom de la réponse, prononcé quand on tourne la molette),
  reliés via des actionNodes virtuels à UUID dérivés (voir les fonctions
  `menuNodeQuestionStageUuid` / `menuNodeOptionsActionUuid` /
  `menuNodeOptionStageUuid` dans ce fichier). C'est cette mécanique précise
  que `build_pack.py` reproduit.
- Spécifications média : images 320×240 (PNG/JPEG/BMP), audio MP3/OGG à
  44100 Hz ou WAV 16 bits mono 32000 Hz.

## Statut testé vs non testé

| Élément | Statut |
|---|---|
| Génération de la structure story.json (Récit/Carrefour → Story/Menu) | ✅ Testé, validé, importé avec succès dans STUdio par l'utilisateur |
| Voix espeak-ng | ✅ Testé, fonctionne (robotique) |
| Voix Kokoro (locale, gratuite) | ⚠️ Abandonné — trop de friction d'installation sous Windows (dépendances torch/soundfile) |
| Voix Google Cloud TTS | ⚠️ Code écrit d'après la documentation officielle, jamais appelé réellement (réseau bloqué côté Claude.ai) |
| rclone vers Google Drive | ⚠️ Non testé |
| Enregistrement vocal réel (Audacity avec étiquettes, ou iPhone Mémos vocaux) | ✅ Confirmé fonctionnel par l'utilisateur |

## Préférences connues de l'utilisateur

- Préfère largement les solutions qui fonctionnent réellement plutôt que des
  pistes séduisantes mais fragiles (a abandonné Kokoro après trop de frictions).
- Veut comprendre précisément ce qui a été testé vs seulement écrit/supposé.
- Demande systématiquement le message d'erreur exact plutôt qu'un résumé quand
  quelque chose ne fonctionne pas.
