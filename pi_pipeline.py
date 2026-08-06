#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pi_pipeline.py — Automatisation complète sur Raspberry Pi :
GitHub (fichier arborescence JSON) -> audio Google Cloud TTS -> pack STUdio -> Google Drive

NON TESTÉ de bout en bout (accès réseau à GitHub/Google/Drive bloqué depuis mon
environnement). Chaque brique (git, build_pack.py, rclone) est un outil stable et
bien documenté pris séparément — c'est leur assemblage précis qui n'a pas pu être
vérifié ici. Testez d'abord une exécution manuelle avant de programmer une tâche
automatique (cron).

Configuration : modifiez les variables ci-dessous, ou passez-les en arguments.
"""
import subprocess, os, sys, argparse, shutil, datetime

def run(cmd, **kw):
    print(f"$ {' '.join(cmd)}")
    subprocess.run(cmd, check=True, **kw)

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--repo', required=True,
                    help="URL du dépôt GitHub contenant votre fichier arborescence JSON "
                         "(ex : https://github.com/votre-compte/mes-histoires.git)")
    p.add_argument('--json', required=True,
                    help="Nom du fichier JSON dans le dépôt (ex : arborescence-test-court.json)")
    p.add_argument('--drive-dossier', required=True,
                    help="Dossier distant rclone où déposer le zip (ex : gdrive:HistoiresLunii)")
    p.add_argument('--travail', default=os.path.expanduser('~/pi-histoires'),
                    help="Dossier de travail local (par défaut ~/pi-histoires)")
    args = p.parse_args()

    os.makedirs(args.travail, exist_ok=True)
    repo_dir = os.path.join(args.travail, 'repo')
    build_script = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'build_pack.py')

    # 1. GitHub : cloner ou mettre à jour
    if os.path.exists(repo_dir):
        print("--- Mise à jour du dépôt ---")
        run(['git', '-C', repo_dir, 'pull'])
    else:
        print("--- Clonage du dépôt ---")
        run(['git', 'clone', args.repo, repo_dir])

    json_path = os.path.join(repo_dir, args.json)
    if not os.path.exists(json_path):
        print(f"ERREUR : {args.json} introuvable dans le dépôt.")
        sys.exit(1)

    # 2 & 3. Construction du pack (audio Google Cloud TTS automatique pour tout,
    #         puisqu'aucun fichier audio n'est fourni manuellement ici)
    audio_dossier = os.path.join(args.travail, 'audio_vide')
    os.makedirs(os.path.join(audio_dossier, 'audio'), exist_ok=True)
    os.makedirs(os.path.join(audio_dossier, 'images'), exist_ok=True)

    horodatage = datetime.datetime.now().strftime('%Y-%m-%d-%Hh%M')
    sortie_zip = os.path.join(args.travail, f'pack-{horodatage}.zip')

    print("--- Construction du pack (voix Google Cloud TTS) ---")
    run(['python3', build_script, 'build', json_path, audio_dossier, sortie_zip, '--tts', 'google'])

    # 4. Envoi vers Google Drive via rclone
    print("--- Envoi vers Google Drive ---")
    run(['rclone', 'copy', sortie_zip, args.drive_dossier])

    print(f"\nTerminé : {sortie_zip} a été envoyé vers {args.drive_dossier}")

if __name__ == '__main__':
    main()
