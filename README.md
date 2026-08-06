# Pipeline automatisé sur Raspberry Pi — configuration (une seule fois)

Trois comptes/outils à préparer avant que ça tourne tout seul. Chaque étape est
un standard bien documenté ; je n'ai pas pu tester l'enchaînement complet depuis
mon environnement (réseau restreint de mon côté), donc testez à la main une
première fois avant de programmer quoi que ce soit en automatique.

## 1. Dépôt GitHub pour vos fichiers JSON

Créez un dépôt (public ou privé) sur github.com, et déposez-y vos fichiers
`arborescence-XXX.json` exportés depuis l'outil. À chaque fois que vous modifiez
une histoire dans l'outil, réexportez et poussez le nouveau JSON dans ce dépôt.

## 2. Google Cloud Text-to-Speech (compte de service, pas juste une "clé")

1. Allez sur https://console.cloud.google.com, créez un projet.
2. Activez l'API "Cloud Text-to-Speech" (menu APIs et services → Activer des API).
3. Créez un **compte de service** (IAM et administration → Comptes de service →
   Créer). Donnez-lui le rôle "Cloud Text-to-Speech > Utilisateur".
4. Générez une **clé JSON** pour ce compte de service (onglet Clés → Ajouter une
   clé → JSON) — un fichier se télécharge, gardez-le précieusement, ne le
   partagez jamais publiquement (ne le mettez pas dans le dépôt GitHub !).
5. Copiez ce fichier sur le Raspberry Pi, par exemple dans
   `~/pi-histoires/google-credentials.json`.
6. Sur le Pi, avant de lancer le script :
   ```
   export GOOGLE_APPLICATION_CREDENTIALS=~/pi-histoires/google-credentials.json
   ```
   Pour que ce soit permanent, ajoutez cette ligne à la fin de `~/.bashrc`.

**Palier gratuit** : Google offre un volume gratuit chaque mois avant facturation
(vérifiez le montant actuel sur la page de tarifs officielle, ça évolue). Pour un
usage familial ponctuel, vous devriez rester largement en dessous.

## 3. rclone (pour envoyer le résultat sur Google Drive)

```
curl https://rclone.org/install.sh | sudo bash
rclone config
```
Suivez l'assistant : `n` (nouveau remote), donnez-lui un nom (ex : `gdrive`),
choisissez `drive` comme type, laissez les champs client_id/secret vides (valeurs
par défaut), et suivez le lien d'autorisation qui s'ouvre dans un navigateur pour
connecter votre compte Google. Une fois fait, `gdrive:` peut être utilisé partout.

## 4. Installer les paquets Python nécessaires sur le Pi

```
sudo apt update
sudo apt install -y python3 python3-pip ffmpeg git
pip3 install google-cloud-texttospeech
```

## Utilisation

Une fois tout configuré :
```
export GOOGLE_APPLICATION_CREDENTIALS=~/pi-histoires/google-credentials.json
python3 pi_pipeline.py \
  --repo https://github.com/votre-compte/mes-histoires.git \
  --json arborescence-test-court.json \
  --drive-dossier gdrive:HistoiresLunii
```

Ça va : récupérer la dernière version de votre JSON sur GitHub, générer tous les
audios avec Google Cloud TTS, construire le pack, et l'envoyer sur Drive.

## Automatiser complètement (optionnel, à faire seulement après un test manuel réussi)

```
crontab -e
```
Ajoutez une ligne pour, par exemple, une exécution chaque nuit à 3h :
```
0 3 * * * GOOGLE_APPLICATION_CREDENTIALS=/home/pi/pi-histoires/google-credentials.json /usr/bin/python3 /home/pi/pi_pipeline.py --repo ... --json ... --drive-dossier gdrive:HistoiresLunii >> /home/pi/pi-histoires/log.txt 2>&1
```

## Ce que je n'ai pas pu vérifier moi-même

- L'appel réel à l'API Google Cloud TTS (le nom de voix `fr-FR-Neural2-C` peut
  avoir changé — si erreur, consultez la liste à jour sur
  cloud.google.com/text-to-speech/docs/voices et ajustez dans `build_pack.py`,
  fonction `google_tts`).
- La configuration rclone avec un vrai compte Drive.
- Le comportement de cron sur votre Raspberry Pi précis.

Si quelque chose ne fonctionne pas exactement comme décrit, montrez-moi le
message d'erreur exact plutôt qu'un résumé — j'ajusterai le code en conséquence.
