# Prompt de reprise — orchestrateur de la remise en sécurité de Sōji

Tu travailles sur Sōji, mon CLI macOS de nettoyage disque, dans :
`/Users/pierrelouis/Documents/Github/soji`.

## Mission et rôle : orchestration uniquement

Je veux que cette conversation principale soit un **orchestrateur**. Lance des sous-agents qui implémentent, testent, intègrent et relisent les corrections sur des branches/worktrees séparés. Toi, tu répartis les responsabilités, suis les résultats pendant le travail, confrontes les preuves, fais corriger les problèmes et contrôles les critères de sortie. Ne prends pas toi-même les tâches d'implémentation ou de résolution des conflits : délègue-les aussi. Ne te contente pas d'un plan ou des déclarations de réussite des agents.

La délégation et le travail parallèle sont explicitement demandés. N'ouvre pas de nouvelles conversations principales pour les sous-tâches. Utilise les vrais outils de sous-agents de l'environnement. Dans T3, utilise `delegate_task` pour des checkouts isolés avec `isolation: "worktree"` et appelle `orchestrator_capabilities` avant la première délégation. Respecte les capacités et les consignes disponibles : ne fabrique pas les worktrees via le shell ou le texte d'une tâche. Si un modèle/provider demandé n'est pas disponible, signale-le sans changer silencieusement. Ne suppose pas que le nom de modèle évoqué par l'utilisateur est disponible.

Tu peux inspecter les diffs, lire les fichiers, les rapports et les résultats pour contrôler le travail. Fais faire les revues de sécurité indépendantes par des agents distincts des auteurs. Sur une nouvelle demande de revue dans T3, crée une nouvelle tâche de revue avec son périmètre exact, plutôt que de relancer un ancien reviewer avec un message. Respecte le mécanisme de suivi indiqué par les outils, sans polling incessant.

Objectif : corriger les **quatre P1 supplémentaires A–D encore reproduits**, préserver les corrections initiales déjà réalisées par Opus et la TUI, faire relire leurs limites sans les réimplémenter, ajouter les régressions manquantes et vérifier l'intégration complète. Aucun nettoyage réel de mon ordinateur n'est autorisé dans cette mission.

## Contraintes absolues

- Pas de suppression, déplacement vers la Corbeille, réparation ou restauration sur mes données ou logiciels réels. Ne lance pas de nettoyage réel, quel que soit le mode, ni les scripts de réparation pour « tester ».
- Toute opération destructive de test reste dans une fixture jetable explicitement créée pour ce test, avec faux home, état séparé, Corbeille jetable et services/outils externes isolés ou mockés. Les tests Git utilisent des dépôts et remotes locaux jetables, sans réseau.
- Ne vide pas ma Corbeille. N'installe/réinstalle pas de logiciel. N'active pas de tâche automatique ou planifiée.
- Préserve les scripts utilisateur `soji-repair.sh` et `soji-restore.sh`. Ne les exécute pas, ne les remplace pas, ne les supprime pas et ne les inclus pas automatiquement dans un commit.
- Mon vault Obsidian est `/Users/pierrelouis/Documents/Obsidian/Main Vault`. Ne passe jamais par computer use pour y accéder. Aucun changement dans ce vault n'est demandé.
- Ne réduis aucune protection pour faire passer un test. L'inconnu doit bloquer les opérations à risque. Un avertissement ne remplace pas un garde-fou.
- Pas de reset destructeur, clean global, stash automatique ou écrasement du travail d'un autre agent. Pas de push, publication ou release sans demande explicite. Des commits locaux ciblés pour organiser l'intégration sont autorisés.

## Sources à lire avant de distribuer le travail

Lis les instructions du repo et ces fichiers dans leur version actuelle :

1. `docs/audit-2026-11-08.md` : audit détaillé, preuves, limites, bugs supplémentaires, état historique, recommandations de régression et validation.
2. `NEXT_STEPS.md`, section `November 8 safety audit (2026-11-09)` : priorités de sécurité et lien vers l'audit. Le paragraphe `Independent review adds four open P1 gates` liste les quatre découvertes de la conversation d'origine.
3. `docs/audit-fixtures/independent_review.py` et `docs/audit-fixtures/rollback_review.py` : copies conservées des scripts de reproduction indépendants. Ce sont des preuves exploratoires, pas encore des tests intégrés. Vérifie leur confinement avant de les exécuter. Ils contrôlent les timestamps historiques des nœuds pour contourner la récence liée au birthtime APFS des fixtures nouvellement créées, mockent les inventaires de l'hôte, mais utilisent de vraies identités de fichiers. Le premier réalise une vraie suppression d'un worktree **jetable** ; le deuxième simule une panne d'écriture du journal et une recréation concurrente du fichier **jetable**. Le chemin du repo dans `sys.path` est fixé à cette machine : adapte-le proprement si nécessaire.
4. `tests/corpus.py`, `tests/corpus_expected.json`, `tests/test_corpus.py`, `tests/test_cleanup_safety.py`, `tests/test_tui_clean.py`, les autres tests spécialisés pertinents.
5. Journal original, à lire sans le modifier :
   `/Users/pierrelouis/.t3/userdata/attachments/a4fc01b6-142f-4170-88ca-4b38cd0211ea-fc6c5297-e5ec-4afd-a3fe-eed87e174372-json.json`
   Nom d'origine : `soji-journal.json` ; SHA-256 : `581cb802b0f4085eb3edb0db561270a58835dc5f01d31861817741ca08b497aa`.

Les numéros de lignes de l'audit sont ceux du snapshot audité et peuvent avoir changé. Retrouve les fonctions ; ne traite pas les références historiques comme la preuve que le code actuel est identique. Si le journal n'est plus accessible, utilise les preuves conservées et signale la limite ; n'invente pas son contenu.

## Incident réel et limites de preuve

Un nettoyage le 8 novembre 2026 a cassé des logiciels installés, notamment Codex. La Corbeille a ensuite été vidée. Le journal est un historique, pas une copie des données : il ne permet pas de restaurer ce qui a disparu de la Corbeille. Ne promets aucune récupération sans autre source effectivement disponible.

Chiffres corrigés : **2 160 entrées, 2 153 déplacements réussis vers la Corbeille, sept échecs**, sur cinq plans. Somme des tailles de tous les candidats : **5 595 066 368 octets**. Somme des entrées réussies : **5 281 062 912 octets**. Aucune de ces sommes ne mesure l'espace réellement libéré.

Plans (heures Europe/Paris) :

| Plan | Première entrée | Entrées |
|---|---|---:|
| `79b34aec11394d739397ffdd72669424` | 8 nov. 00:15 | 9 |
| `046cd36618c84dc1a18e012bc3c5b8e8` | 8 nov. 01:00 | 1 370 |
| `217796c9d0574311adef02b51a9b24c5` | 8 nov. 01:42 | 600 |
| `bcfcf503f5ac47f3a43de251c6694c43` | 8 nov. 01:43 | 69 |
| `0ea353e2e5084800b6172dc73d7a3bdc` | 8 nov. 20:13 | 112 |

L'ancien journal n'a ni mode/version, ni règle/seuil/raison. Des messages d'échec révèlent careful pour `046cd366` et balanced pour `0ea353e2`. N'attribue pas un mode aux autres succès sans preuve. Le journal établit les opérations enregistrées, pas chaque panne d'application ni l'identité exacte du binaire historique.

## Travail déjà accompli dans les trois conversations

### Conversation d'origine : quatre bugs supplémentaires reproduits

Revue indépendante du code et du journal ; aucune modification du moteur pendant cette revue, aucun nettoyage réel. Quatre reproductions sur fixtures, transmises à l'autre thread puis ajoutées à son audit :

**A. P1 — suppression définitive de données ignorées dans un worktree.**

- `GitInspector.inspect(..., worktree=True)` utilisait `git status --porcelain --untracked-files=normal`. Cela ne recense pas les fichiers ignorés.
- Repro : dépôt committé/poussé sur remote local, worktree détaché fusionné, `.gitignore` contenant `local-data/`, fichier unique `local-data/irreplaceable.txt`.
- Le Scanner sélectionne le worktree reconnu `~/.codex/worktrees/audit`, âgé artificiellement de 30 jours, sans hold dans **les trois modes**. Le garde Git le déclare vérifié/propre/fusionné/poussé.
- `Cleaner.tool_action(git-worktree)` exécute réellement `git worktree remove` sans `--force`, et le fichier unique disparaît avec le worktree.
- Cette suppression définitive passe par les options explicites permanent/tool execution. La TUI X, limitée à la Corbeille, ignore cette action : ne confonds pas les chemins d'exécution.
- Corriger l'inventaire/validation des fichiers ignorés, refuser toute donnée non positivement classée jetable et toute inspection incomplète. Ajouter des cas ignorés base de données/notebook/export, et un cas positif réellement sûr. Vérifier la survie des fichiers au niveau de l'exécution réelle en fixture.

**B. P1 — perte du contexte des versions épinglées pendant la vérification fraîche.**

- `Cleaner.fresh` construit un Scanner limité à la cible/famille de versions. `ProjectPins` ne lit que `scanner.nodes`.
- Repro : scan de tout le faux home, plan de suppression de nvm `v18.20.0`, puis création de `project/.nvmrc` contenant `18.20.0`.
- Nouveau scan complet : refuse avec `Version pinned by a project`. Vérification fraîche de l'ancien plan : **accepte**, identités de fichiers inchangées.
- Préserver/reconstruire le périmètre des dépendances de politique, découvrir aussi les nouveaux fichiers de pin ; ne pas seulement rejouer une liste historique de pins. Refuser si la découverte complète nécessaire ne peut pas être établie.
- Tests scan → plan → nouveau pin → fresh/apply, pins existants/supprimés, inventaire incomplet et changements entre phases.

**C. P1 — alias nvm en chaîne : version par défaut non protégée.**

- `SpecializedRules.active` suivait les symlinks et comparait des chaînes littérales, sans résoudre les alias texte nvm.
- Repro : `alias/default` = `lts/*`, `alias/lts/*` = `lts/hydrogen`, `alias/lts/hydrogen` = `v18.20.0`, avec v22/v24 installés. Le Scanner sélectionne v18 en aggressive, sans hold.
- Les références LTS dans les alias et `.nvmrc` sont documentées par nvm : https://github.com/nvm-sh/nvm/blob/master/README.md#long-term-support .
- Résoudre les alias de manière bornée, sans traversée hors du périmètre, avec détection de cycles ; refuser en cas d'incertitude. Tests alias direct/chaîne, cycles, alias manquant/illisible, traversée et alias changeant pendant fresh.

**D. P1 — rollback permanent écrasant un nouveau fichier utilisateur.**

- `Cleaner.move(..., want_permanent=True)` renomme la cible en `.soji-removing-*`, journalise, puis supprime.
- Si la journalisation échoue après staging et avant `removal_started=True`, le rollback utilisait `os.rename(staged, original)` avec remplacement possible.
- Repro : staging d'un ancien cache ; simulation d'une application recréant le fichier original avec `NEW UNIQUE USER DATA` ; panne d'écriture injectée au checkpoint `phase=removing`. L'opération indique un échec mais le rollback écrase les nouvelles données avec l'ancien cache.
- Utiliser une restauration atomique exclusive sans remplacement. Un test d'existence suivi d'un rename ordinaire ne suffit pas. En cas de conflit, conserver **les deux objets**, documenter le staging/conflit et ne pas annoncer une restauration réussie.
- Tests conflit fichier/dossier, rollback normal, panne du rollback et survie des deux contenus. Ce défaut appartient au chemin permanent, pas au simple déplacement TUI vers la Corbeille.

Ces quatre défauts sont confirmés par fixtures ; aucun n'est présenté comme une cause démontrée des dégâts du journal original.

### Autre thread : avertissements, corrections TUI et documentation

Le thread d'audit/TUI a terminé ses deux interventions. Il a modifié `soji_cli/tui.py`, `tests/test_tui_clean.py`, `NEXT_STEPS.md` et créé `docs/audit-2026-11-08.md`.

Travail réalisé :

- Avertissements visibles à la sélection du mode, avant confirmation et après nettoyage : risque de casser logiciels/runtimes/dépendances en aggressive ; groupes à risque ; undo possible seulement tant que les objets existent dans la Corbeille.
- Correction d'une confirmation qui tronquait les chemins sans possibilité de défiler. Confirmation/résultats défilent maintenant ; les avertissements précèdent les chemins. Navigation flèches, J/K, Page Up/Down sans annuler immédiatement la confirmation.
- Fin du message trompeur « freed » calculé à partir des octets déplacés vers la Corbeille. Affichage des octets déplacés et explication que l'espace peut rester occupé. La clé interne `freed` a été conservée pour compatibilité, sans en faire une mesure disque.
- Correction des instructions d'undo : le panneau consommait U pour se fermer, alors que le texte promettait une restauration sur une seule pression. Il explique maintenant de fermer le panneau, puis presser U pour **tenter** l'undo. Ne promets pas le succès si les vérifications d'identité/parent ou la Corbeille l'empêchent.
- Audit détaillé des défauts initiaux, des trois problèmes TUI et des quatre P1 indépendants. La seconde intervention a seulement enrichi la documentation avec nos preuves ; elle n'a pas réexécuté nos suppressions en fixtures ni corrigé ces quatre P1.

Validation rapportée sur **son snapshot**, avant les changements moteur apparus ensuite :

- Tests TUI ciblés : 16, OK.
- Suite complète : `Ran 268 tests`, OK, **deux skipped** (ne dis pas que les 268 ont tous été exécutés avec succès).
- `git diff --check` : OK.
- Écran curses mocké, pas de validation sur un terminal physique ; pas de rebuild du binaire/release ; pas de golden corpus régénéré.

Ces résultats ne couvrent pas les corrections moteur apparues ensuite ni les nouvelles régressions à intégrer. Ils ne certifient pas la sécurité de mon home réel.

## Mise à jour après lecture du thread Opus 5.5 terminé : éviter les doublons

Le thread Opus a été retrouvé et son bilan final a été lu :
<t3-thread://v2/935f6b6d-a10f-4995-8303-979901abeddd/23606d1e-4aaf-46aa-a358-4e985745ba81>

Il a terminé le 9 novembre à 18:54 UTC. Il revendique les corrections des **cinq bugs initiaux et du retry Obsidian**, avec code, 15 nouveaux tests `tests/test_nov8_regressions.py`, 12 nouvelles lignes du golden et trois tests corpus supplémentaires. Il rapporte : suite complète `Ran 285 tests`, OK, deux skipped ; 27 tests d'index natif réussis ; 12 des 15 nouvelles régressions échouent sur l'ancien HEAD, les trois cas de conservation passent comme prévu. **Rien n'est committé.**

Il a aussi trouvé puis exclu `~/Library/Application Support/Zed/prettier/node_modules` et élargi l'exclusion des règles projet sous `~/Library`. Cela mérite une revue des faux positifs/négatifs, pas une seconde implémentation par défaut. Il indique avoir effectué des scans réels en lecture seule, dont environ 560 000 entrées, sans sélection dans les groupes dépendances/build/toolchains/extensions ; cette observation ne certifie pas toutes les racines ni tous les usages.

Lors de cette vérification de chevauchement, la conversation d'origine a **réexécuté les 15 tests de novembre : tous passent**. Elle a aussi relancé les deux scripts indépendants archivés, uniquement dans leurs répertoires temporaires : **A, B, C et D se reproduisent encore sur le code après Opus**, avec les mêmes résultats (worktree sélectionné dans les trois modes et supprimé avec ses données ignorées ; nouveau pin manqué par fresh ; alias nvm ignoré ; rollback écrasant les nouvelles données). La suite complète de 285 tests et les 27 tests natifs sont des résultats rapportés par Opus, pas réexécutés pendant cette vérification.

| Sujet | État de reprise | Action à déléguer |
|---|---|---|
| Bugs initiaux 1–5 et retry Obsidian | Implémentés par Opus, 15 régressions repassées ici | **Revue indépendante ciblée** ; corriger seulement une lacune démontrée |
| Défilement, messages de risque/Corbeille, octets déplacés, instructions U | Déjà corrigés par le thread TUI | Préserver et tester à l'intégration ; aucune réécriture prévue |
| P1 A : worktree et données ignorées | Toujours reproduit après Opus | Implémentation + tests |
| P1 B : périmètre des pins pendant fresh | Toujours reproduit après Opus | Implémentation + tests |
| P1 C : alias nvm en chaîne | Toujours reproduit après Opus | Implémentation + tests |
| P1 D : rollback qui écrase | Toujours reproduit après Opus | Implémentation + tests |

L'ancien audit contient des déclarations historiques « baseline unresolved ». Elles ne signifient plus que les corrections initiales restent à écrire. Le changelog `NEXT_STEPS.md` section `Changelog: November 8 fixes (2026-11-09)` décrit le travail Opus. Conserver la chronologie et relier les preuves plutôt que mettre les deux textes en concurrence.

## Attention : workspace partagé, corrections Opus et TUI non committées

Au moment de vérifier cette reprise, HEAD était toujours `9d85b782b7df9205d76711c0ebabbf72a2e5a4dd`, mais le checkout était **sale**. Les changements moteur précédemment non attribués proviennent du thread Opus terminé ; ils sont distincts du patch TUI. Préserve les deux ensembles. Opus signale qu'un stash temporaire a brièvement emporté les changements partagés, puis qu'il les a restaurés et fusionné NEXT_STEPS. Ne refais pas ce stash ; contrôler la cohérence de la base commune est nécessaire.

Fichiers modifiés observés :
`soji_cli/__main__.py`, `catalogs.py`, `cleanup.py`, `data/hints.json`, `engine.py`, `specialized.py`, `tui.py`, `tests/corpus.py`, `tests/test_engine.py`, `tests/test_project_activity.py`, `tests/test_tui_clean.py`, `NEXT_STEPS.md`.
Nouveaux fichiers observés : `soji_cli/installs.py`, `tests/test_nov8_regressions.py`. `soji_cli/data/README.md`, `tests/corpus_expected.json` et `tests/test_corpus.py` ont aussi été modifiés par Opus. Les docs et scripts de reproduction de cette transmission peuvent aussi être non suivis.

Le diff Opus contient : détection des arbres installés et vrais projets, unités atomiques, holds des exécutables actifs, métadonnées de runtimes Codex, plancher de sessions 24 h et détection de projets déplacés, métadonnées du journal, classification de récupération et temporisation de 24 h après refus d'usage actif.

**Ce sont des corrections réalisées avec tests, à préserver et relire, pas à recommencer.** Fais vérifier les limites de chaque exigence et l'intégration. Réouvre une correction initiale uniquement sur preuve d'un défaut résiduel. Ne confonds pas absence de revue indépendante complète et absence d'implémentation.

## Exigences initiales : référence pour la revue des corrections Opus, pas tâches de réimplémentation

Les six rubriques ci-dessous conservent le cahier des charges et les points de vigilance. Elles servent au reviewer de la baseline. **N'ouvre pas six nouveaux chantiers pour réécrire ce qu'Opus vient de livrer.** Tout manque doit être démontré sur le code actuel, puis traité dans un périmètre précis.

### 1. Runtime actif fragmenté par Toolchains and SDKs

Plan `0ea353e2`, balanced 20:13 : environ 50 objets/~990 MB à l'intérieur de `~/.cache/codex-runtimes/codex-runtime-install-L2Mqle/` supprimés séparément : archive Node, `payload/codex-primary-runtime/dependencies/node/bin`, Python 3.12, `libpython3.12.dylib`, modules JS et bibliothèques numpy/pandas/lxml. Des siblings étaient refusés pour projet actif 0 h contre 336 h/168 h : garde d'activité incohérent entre règles.

- Toutes les règles, Toolchains compris, doivent respecter les protections d'activité pertinentes : projet, fichiers ouverts et processus.
- Une installation runtime/toolchain est atomique : racine entière ou rien. Aucun fichier/sous-dossier interne sélectionné. Toute activité/refus pertinent d'une partie protège l'ensemble.
- Protéger les runtimes courants/référencés/en usage ; identifier positivement la supersession. Ne pas confondre version maximale, date récente ou absence de metadata avec preuve suffisante de désuétude. Les installs `wDayCH`, `G1C0iB`, `WZLpxw`, `sktXXo`, `71EdN2`, `FNGf96` étaient considérées comme anciennes par l'utilisateur ; leur suppression ne constitue pas à elle seule une preuve de supersession.
- Tester tous les modes, racine et sous-chemins, metadata absente/malformée, rangs, références, processus et activité d'un descendant, refus partiels et revalidation.

### 2. Dépendances livrées avec des logiciels prises pour des projets

Cas à reproduire dans un faux home :

- `~/.vscode/extensions/ritwickdey.liveserver-5.7.10/node_modules`
- `~/.vscode/extensions/oderwat.indent-rainbow-8.3.1/node_modules`
- `~/.vscode/extensions/esbenp.prettier-vscode-12.4.0/node_modules`
- `~/.vscode/extensions/pranaygp.vscode-css-peek-4.4.3/{server,client}/node_modules`
- `~/.vscode/extensions/ms-python.python-2026.10.0-darwin-arm64/out/client/node_modules`
- `~/.config/raycast/extensions/<uuid>/node_modules`
- `~/Library/Application Support/Zed/extensions/work/{html,emmet}/node_modules`
- `~/Library/Application Support/discord/app-0.0.411/modules/discord_spellcheck-1/discord_spellcheck/node_modules`
- `~/.t3/tools/expo-device-hub/0.15.3/node_modules`

Exclure les arbres installés : vscode/insiders, cursor, windsurf, Raycast, Zed, Electron `Application Support/*/app-*`, `.t3/tools`, bundles `.app`, manifestes d'app/extension (`engines.vscode`, `publisher`, Raycast...). `out`, `dist`, `modules` de ces arbres sont du code livré, pas des sorties de build jetables. Une simple présence de package.json ne prouve pas un projet de développement. Définir une preuve prudente de vrai projet (VCS/lockfile/contexte) sans laisser l'ascendance VCS d'un dossier parent annuler une exclusion d'installation connue.

Conserver des cas positifs : vrais projets de développement inactifs et caches dédiés `Code/CachedExtensionVSIXs`, `CachedData`, `GoogleUpdater/crx_cache`, Electron `Cache`, `Code Cache`, `GPUCache` quand tous les gardes passent. Ne pas surbloquer tous les caches parce qu'ils vivent dans Application Support.

### 3. Sessions d'un projet renommé rétrogradées comme projet disparu

`levo-terminal` a été renommé `soji`. Des sessions Claude sous `.claude/projects/-Users-pierrelouis--t3-worktrees-levo-terminal-…` ont été prises après 3,2 h (`bcfcf503`) ; celles de `…-Documents-Github-levo-terminal/` après 19–20 h (`0ea353e2`). Balanced attendu : 48 h sessions/24 h sidecars.

- Ne pas déduire « projet disparu » de la seule absence du cwd historique. Chercher déplacement/renommage via identité de dépôt, remote/commit racine, worktrees enregistrés et historique cwd pertinent. Ne pas remplacer une identité de dépôt par une simple égalité du nom final de remote.
- Incertitude : aucune rétrogradation. Plancher dur de 24 h à careful/balanced, même après jugement agent ou downgrade, avec couverture des sessions composées et sidecars.

### 4. Journal incomplet pour auditer les décisions

Enregistrer mode/version Sōji par plan et règle/seuil effectif/raison par entrée, y compris raison de jugement (`levels.reason`) et distinction politique du plan/vérification fraîche. Couvrir succès, refus, actions natives et sessions composées. Compatibilité de lecture des anciens journaux ; ne pas inventer leur mode manquant.

### 5. Undo dépendant de la Corbeille

`soji journal` doit distinguer les objets dont `trashedTo` n'existe plus : « unrecoverable (Trash emptied) ». L'existence seule n'assure pas l'identité/restaurabilité : ne pas surpromettre. Vérifier statut des membres, états partiels, objets remplacés, erreurs de permissions et méthodes permanentes.

Conserver/améliorer les messages de confirmation et fin d'opération déjà ajoutés. Si les seuils/jugements sont dangereux, refuser au moteur plutôt que se contenter d'une confirmation supplémentaire.

### 6. Refus d'usage actif instable (cas Obsidian)

Même Code Cache Obsidian refusé dans `046cd366`, puis `217796c9`, ensuite déplacé dans `bcfcf503`. Le journal ne prouve pas qu'Obsidian tournait sans interruption : absence de snapshot processus. Tester que le propriétaire actif protège le cache même sans fichier momentanément ouvert, que les sources indisponibles ne permettent pas une acceptation dangereuse, et que des retries ne contournent pas un refus d'usage actif. Évaluer la temporisation actuellement ajoutée, son périmètre et sa revalidation ; pas de sécurité reposant uniquement sur une correspondance fragile de chaînes d'erreur.

## Organisation demandée : branches isolées, responsabilités nettes

Adapte le nombre de sous-agents aux slots réellement disponibles. Exécute par vagues si nécessaire, sans mélanger les scopes ni créer une armée d'agents sans suivi.

### Phase 0 — sous-agent intégrateur : établir une base commune sans perdre le travail

Avant de lancer les branches de correction, délègue à un intégrateur l'inventaire du checkout sale, des instructions, du diff et des fichiers nouveaux. Il doit déterminer s'il reste du travail actif d'autres agents et éviter de figer un fichier à moitié écrit. Faire une base locale identifiable avec les changements existants conservés, en séparant scripts utilisateur et artefacts privés. Aucun `git add .` aveugle. Les worktrees partent de cette base commune explicite : partir de HEAD seul **n'importe pas les modifications non committées**. Ne répartis pas des agents sur une base qui omet le patch TUI ou `installs.py`.

L'orchestrateur contrôle cet inventaire et garde un tableau : bug, propriétaire, branche, tests attendus, preuve, revue, état d'intégration.

### Phase 1 — implémentations déléguées

| Agent / branche suggérée | Périmètre | Points de coordination |
|---|---|---|
| `review/opus-baseline` | Revue indépendante des corrections Opus exigences 1–6 et de leur couverture ; rapport de lacunes prouvées, sans réimplémentation systématique | `installs.py`, moteur, sessions, journal, retry, tests novembre/corpus ; créer une tâche de correction seulement si un défaut résiduel est confirmé |
| `fix/version-policy-context` | P1 B–C : pins externes lors de fresh, alias nvm et résolution conservatrice | Peut toucher `cleanup.py`/`specialized.py` aussi : worktree séparé, interfaces convenues, intégration séquentielle |
| `fix/worktree-data-safety` | P1 A : fichiers ignorés, sécurité Git vs sécurité du contenu, garde à l'exécution | `gitstate.py`, action worktree ; aucun test sur un worktree utilisateur |
| `fix/permanent-rollback-safety` | P1 D : rollback atomique sans écrasement, conflits, journal des échecs | `cleanup.py` partagé avec d'autres branches ; diffs ciblés et intégration contrôlée |

Les auteurs de corrections A–D doivent ajouter des tests avant/après significatifs et conserver les correctifs Opus/TUI. Le reviewer de la baseline produit d'abord un rapport : il ne réécrit pas ces correctifs par défaut. Chaque agent reçoit les contraintes de sécurité et les sources nécessaires, pas seulement une ligne de mission. Personne n'écrit dans le checkout d'un autre. Les conflits ne se résolvent jamais en choisissant arbitrairement « ours/theirs » ou en abandonnant un garde-fou.

### Phase 2 — revue indépendante et intégration

- Délègue les revues à des agents qui n'ont pas écrit les corrections examinées. Fournis la base/head exacte, le diff, le bug, les obligations et les tests.
- L'intégrateur applique les branches dans un ordre explicite ; en cas de conflit, les auteurs expliquent les invariants à préserver et l'intégrateur résout dans sa branche.
- Ajoute une revue transversale du résultat intégré : pas seulement la somme des revues de branches. Vérifier particulièrement fresh vs scan complet, caches/TTL invalidés, jugements agents, index réutilisé, actions natives et accès par racine/sous-chemin.
- L'orchestrateur lit les preuves au fil de l'eau, fait corriger les findings et ne coche « terminé » qu'après tests et revue sur le bon SHA. Pas de réparation directe par l'orchestrateur pour masquer un désaccord entre agents.

## Régressions et critères de sortie

Chaque bug doit avoir un test qui échoue sur le comportement défectueux et passe après correction, ou une démonstration claire qu'une correction existante le couvre déjà. Couvrir les vrais chemins signalés via faux home, careful/balanced/aggressive, refus et cas positifs. Incorporer les cas représentatifs dans `tests/corpus.py` et le golden `tests/corpus_expected.json`, en plus des tests unitaires/intégration ciblés.

Ne régénère pas le golden pour faire disparaître un échec sans comprendre le diff. Si le changement est intentionnel :

```sh
SOJI_UPDATE_CORPUS=1 python3 -m unittest tests.test_corpus
```

Puis revoir chaque sélection nouvelle/disparue. Éviter les tests qui mockent précisément le garde que l'on prétend vérifier. Les wrappers de services externes peuvent être mockés, mais il faut aussi tester la classification réelle, la revalidation et les mutations de fixtures. Corriger un fixture pour y ajouter un lockfile peut être légitime ; ne pas modifier simplement les attentes pour dissimuler une régression.

Sur le résultat intégré, faire exécuter au minimum :

```sh
python3 -m unittest discover -s tests -q
git diff --check
```

Lancer les validations natives disponibles et pertinentes seulement après inspection de leur confinement. Pas de broad scan/nettoyage réel comme substitut aux tests. Documenter les tests skipped, dépendances manquantes, absence de validation sur terminal physique et limites natives/macOS.

Actualiser `docs/audit-2026-11-08.md` et `NEXT_STEPS.md` avec un état **actuel** par bug, sans effacer les preuves historiques : corrigé, partiellement corrigé ou ouvert, tests, SHA et limites. Ajouter une courte note CHANGELOG si le repo en a un ; sinon NEXT_STEPS suffit. Faire vérifier les informations d'aide et avertissements pour qu'ils correspondent au moteur final.

Ne construis pas/installe pas une nouvelle release implicitement. Si un artefact est produit pour validation isolée, distinguer le code source testé du binaire installé. N'annonce jamais que l'application installée est réparée parce que la suite Python passe.

## Réponse finale attendue de l'orchestrateur

En français, me donner :

1. Tableau des bugs initiaux + quatre P1 indépendants + trois corrections TUI : état, correction, fichiers, test, revue.
2. Branches/commits intégrés et état exact du checkout, sans attribuer les modifications préexistantes aux mauvais agents.
3. Commandes de validation réellement exécutées, résultats exacts et skips ; réserves restantes.
4. Nouveaux bugs trouvés pendant la mission, distingués des défauts déjà connus.
5. Ce que je dois vérifier maintenant sur mes logiciels, sans me faire exécuter un nettoyage pour savoir s'ils fonctionnent.
6. Plan de validation en escalier : fixtures → intégrations macOS dans compte/VM jetable sans données partagées précieuses → revue de plans en lecture seule → seulement ensuite éventuelle proposition limitée de nettoyage réel, explicitement autorisée et avec récupération indépendante vérifiée.

Ne recommande pas aggressive parce que son avertissement a été amélioré. N'affirme pas non plus que careful est universellement sûr : le worktree avec fichier ignoré était sélectionné dans les trois modes. Termine avec une décision de sécurité motivée par les preuves et les blocages restants, sans me demander de valider du travail encore abstrait.
