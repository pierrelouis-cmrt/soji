# État final local de sécurité — 2026-11-09

## État courant : intégré dans main, sans publication

L'intégration locale est terminée. `main` a été avancée **uniquement par
fast-forward** depuis `21ce74904430bd8293036239343de635f72b0729` vers
`cb8865c73b1b219518b8aecbebbb25c4768b7e55`, branche source
`integration/safety-sol-20261109`. Un commit final de documentation suit ce
fast-forward ; aucun code, test, golden ou helper n'est modifié par ce commit.
Le SHA exact de ce dernier commit est donné dans la réponse de finalisation.

**Code/tests/native revus : `e8a7237c2ea079834eebd6328e6a18b011d34d3b`.**
Les arbres `soji_cli`, `tests`, `native` de main sont identiques à cette révision.
La revue finale décide **APPROVE**, aucun P1/P2 bloquant dans son périmètre.
Rapport original copié sans modification depuis le commit de preuve/documentation
`bc93f33a50b997651dfecbddc76d2eff80b65c92` :
[revue indépendante finale](FINAL_INDEPENDENT_REVIEW_2026-11-09.md).
Ses tests de preuve supplémentaires ne sont pas cherry-pickés dans main.

`origin/main` reste localement à `21ce74904430bd8293036239343de635f72b0729`.
Aucun fetch/push, PR, release, installation ou rebuild du binaire installé.
Main est en avance de 18 commits locaux après le commit final de documentation
(17 commits intégrés, puis cette finalisation). Le binaire installé n'est pas
réparé ou certifié par cette intégration de sources.

## Exigences, bugs et TUI : état actuel

| Sujet | État et garde intégré | Preuves / limites |
|---|---|---|
| 1. Runtime actif fragmenté / supersession | Racines atomiques, refus des intérieurs, activité/processus résolus, référence Codex positive avec metadata cohérentes ; références génériques inconnues retenues | Tests runtime/novembre et marqueurs. Ne certifie pas toutes les autres familles ou futurs formats. |
| 2. Dépendances livrées prises pour projets | Installations explicites prioritaires sur VCS/locks, toute l'ascendance inspectée ; vrai propriétaire de projet avec son VCS + lock | Cas profonds, scan partiel, fresh et caches invalidés ; vrais projets et caches dédiés restent couverts. |
| 3. Sessions de projet renommé / cwd absent | Seuils normaux non abaissables par agent quand aucune disparition n'est prouvée ; membres composés conservés ; plancher 24 h careful/balanced | **Preuve positive de projet disparu non implémentée** ; repli conservateur assumé. |
| 4. Journal de décision incomplet | Mode/version, provenance agent, politiques plan/fresh et preuves des verifiers natifs ; erreurs checkpoint conservées | NaN/Infinity/bool et timestamps invalides des entrées/membres bloquent via history-unknown. Journal durable non garanti en panne persistante. |
| 5. Undo après Corbeille vidée / identité | Distinction absent, illisible, remplacé, partiel ; copie staging conservée signalée | Aucune promesse de récupération après vidage ; le journal n'est pas une sauvegarde. |
| 6. Refus d'usage actif instable | Codes structurés, recouvrement parent/enfant, cooldown 24 h sans renouveler l'horloge ; inventaire apps inconnu bloque ; uninstall actif aussi mémorisé | Positifs d'expiration finis conservés. Les snapshots ne verrouillent pas les futurs usages. |
| A. Perte de données ignorées d'un worktree | **Nettoyage des worktrees désactivé** dans tous les modes, décisions moteur, fresh/apply, anciens plans sans action et tool_action direct | Notes uniques, dépôt bare et writer après inspection : routes bloquées par politique. GitInspector reste diagnostique, pas preuve de jetabilité. |
| B. Pins perdus pendant fresh | Redécouverte live des racines du plan + home ; scope protégé/privé, profondeur/montage non inspecté = inconnu, familles concernées retenues | Correct mais coûteux : budget souple par item de 120 s / 5 M entrées ; peut rendre le nettoyage de versions indisponible. |
| C. Alias nvm en chaîne | Résolution bornée et confinée ; cycles, traversal, liens et metadata incertaines retiennent la famille | Positifs actifs/inactifs et changements entre scan/fresh couverts. |
| D. Rollback permanent écrasant un nouveau fichier | Staging et rollback atomiques exclusifs, aucun remplacement de secours ; conflits préservent les deux objets | Tests fichiers/dossiers, checkpoint, restauration d'une autre identité et indisponibilité du primitif. |
| TUI 1. Avertissements | Risques aux étapes mode/confirmation/fin ; groupes à risque partagés avec le moteur ; undo limité à la Corbeille | Amélioration de l'information, pas autorisation de nettoyage. |
| TUI 2. Chemins tronqués | Confirmation défilable, accès aux chemins longs et avertissement final | Validation simulée ; pas de terminal physique revendiqué. |
| TUI 3. Résultats / U / retry | Octets déplacés, pas espace libéré ; instruction U ; undo en échec reste réessayable sans refaire les succès | Tests TUI et restauration composée ; pas de garantie après vidage. |

## Provenance des commits intégrés

Base `21ce749` : travail Opus/TUI et scripts utilisateur préexistants, conservés.
Les commits originaux ont été préservés par cherry-picks séparés, dans l'ordre
explicitement demandé ; aucun commit de preuve-only du reviewer n'a été fusionné.

| Lot | Commits originaux | Commits intégrés |
|---|---|---|
| D | `689174e`, `9651c55` | `2e705c2`, `a56f54c` |
| Journal / undo / refus | `16c0699` | `3341cc3` |
| A puis revue A | `52bb0e5`, `68aff51` | `c8af7ec`, `ab538b9` |
| B+C | `e802e92` | `7f8eb5c` |
| Baseline puis preuves/doc | `02155a8`, `5f81022` | `84aaa86`, `7e9ff6f` |
| Corrections d'intégration | Nouvelles corrections locales | `191ec58`, `d26dd11`, `8d8e6cb` |
| Cinq findings de cross-review | Nouvelles corrections locales | `abdfc1c`, `fc7d5ee` |
| P1 résiduel du marqueur symlink | Nouvelle correction locale | `e8a7237` |
| Rapports historiques d'intégration | Documentation | `82da248`, `8a5418d`, `cb8865c` |

Les conflits corpus ont conservé l'isolation Git, les mocks natifs/apps et tous
les fixtures A/B/C/baseline ; les goldens ont été fusionnés sémantiquement puis
leurs changements intentionnels inspectés. La dernière correction symlink n'a
modifié aucun golden. Détails :
[statut intégré](INTEGRATED_SAFETY_STATUS_2026-11-09.md),
[suivi des cinq findings](INTEGRATED_REVIEW_FOLLOWUP_2026-11-09.md),
[dernier correctif marqueur](MARKER_SYMLINK_FOLLOWUP_2026-11-09.md).

## Validation indépendante exacte, sans nouvelle exécution ici

Le reviewer a exécuté sur les arbres revus, avec zéro skip :

- Preuve originale inchangée : **1 test OK**, 0,414 s.
- Trois tests indépendants supplémentaires (chaînes, scope partiel/cache, index) : **3 OK**, 1,491 s.
- Suite ciblée : **189 tests OK**, 85,634 s.
- Suite complète native : **462 tests OK**, 135,528 s, exit 0.

Commande complète **du reviewer**, non relancée pour cette finalisation docs-only :

```
SOJI_NATIVE_WALK_HELPER=/private/tmp/soji-native-integration-20261109/soji-native SOJI_TEST_NATIVE=/private/tmp/soji-native-integration-20261109/soji-native python3 -m unittest discover -s tests -q
```

Le rapport final conserve les quatre commandes exactes, les logs et le confinement.
L'auteur avait aussi exécuté 462 tests OK sans skip sur `e8a7237` (135,225 s).
La finalisation présente exécute seulement les contrôles Git / identité des arbres,
la copie du rapport et les modifications documentaires ; **aucune nouvelle suite
complète n'est revendiquée**. Helper jetable et cache sous `/private/tmp`, non
installés. Aucun inventaire réel d'apps/scan/Trash natif utilisé comme substitut.

Avant fast-forward, le checkout primaire avait exactement main à `21ce749` et
le seul fichier non suivi attendu : ce document de statut du parent. Aucun travail
utilisateur inattendu n'a été écrasé. Son contenu antérieur est conservé ci-dessous
comme historique, et n'énonce plus l'état courant. Le rapport d'approbation est
une copie exacte du blob du reviewer ; aucune nouvelle preuve n'est cherry-pickée.

## Limites et suite de validation

Pas de certification universelle de tous les formats/familles atomiques, de TCC
réel, du terminal physique ou des applications installées. Les formats de
marqueurs inconnus et scopes pins incomplets coûtent volontairement de la
disponibilité ; absence optionnelle ne prouve pas supersession. Les courses
processus/fichiers après snapshot subsistent hors route worktree désactivée.
L'inférence positive de projet disparu reste absente. Le journal historique
n'est pas une sauvegarde et une panne durable peut empêcher son écriture.

Validation en escalier, sans nettoyage réel implicitement autorisé :

1. Fixtures isolées : réalisées, y compris suites natives indépendantes.
2. Intégration macOS dans un compte/une VM jetable sans données précieuses partagées.
3. Revue des plans en lecture seule, périmètre limité et état des logiciels vérifié
   sans lancer un nettoyage pour vérifier qu'ils fonctionnent.
4. Seulement ensuite, proposition limitée de nettoyage réel, **séparément et
   explicitement autorisée**, avec récupération indépendante vérifiée avant action.

Ni careful ni aggressive n'est déclaré universellement sûr. Rien n'a été poussé,
installé ou publié ; aucun scan/nettoyage/Trash/réparation/restauration de données
réelles. `soji-repair.sh` et `soji-restore.sh` restent identiques à `21ce749` et
n'ont pas été exécutés. Les autres worktrees sont préservés.

---

## Historique conservé — snapshots antérieurs, non état courant

Le texte suivant est le handoff du parent avant intégration finale. Ses mentions
« main reste à 21ce749 », « en cours », « ouvert » et demandes de reprise sont
historiques. L'état courant et la décision de revue sont exclusivement ceux
ci-dessus.

# État de l'orchestration sécurité — 2026-11-09 (pause pour limite d'usage)

## Reprise Sol 6.1 — travail en cours

La pause décrite ci-dessous est historique. Reprise autorisée par l'utilisateur avec Sol 6.1 ; anciens agents Opus arrêtés, leurs worktrees conservés. `main` reste à `21ce749` pendant la validation isolée. Aucun nettoyage réel, push ou release.

| Lot | Commits locaux livrés | État actuel |
|---|---|---|
| A, suivi worktrees | `52bb0e5` → `68aff51` | Revue indépendante : **changements requis** ; notes uniques dans node_modules, dépôt Git bare imbriqué et écriture après inspection sont supprimés. Preuves `1fe232c`. Suppression permanente des worktrees à désactiver dans l'intégration, avec refus moteur et exécution des anciens plans. |
| D + journal/undo/refus/TUI | `689174e` → `9651c55` → `16c0699` | Implémentation livrée ; revue indépendante en cours. Suite auteur : 320 tests, 10 skipped. |
| B+C | `e802e92` | Revue indépendante neuve en cours. |
| Runtimes/dépendances/sessions | `02155a8` + `5f81022` | Livrés ; revue et intégration en cours. Suite auteur : 325 tests, 10 skipped. Sessions : seuils normaux conservés par prudence ; preuve positive de projet disparu non implémentée. |
| Intégration | tâche Sol isolée | Assemble les branches, traite les findings A, valide Python/natif en fixtures et actualise les documents. Revue transversale encore requise. |

Les résultats d'auteurs ci-dessus ne constituent pas une validation indépendante du résultat intégré. Les 10 skips sont 8 tests du walker natif et 2 tests de récupération native opt-in. Les risques d'autres familles de versions et les limites d'identité historique sont documentés par l'auteur dans `docs/BASELINE_SOL_2026-11-09.md` sur `5f81022`.

---

Suite de `docs/SAFETY_ORCHESTRATOR_PROMPT.md`. Base commune : `21ce749` (main = origin/main, checkout propre ; contient déjà Opus + TUI + docs + fixtures + `soji-repair.sh`/`soji-restore.sh` committés par l'utilisateur). Aucune branche n'est encore intégrée dans `main`. Rien n'est poussé. Aucun nettoyage réel n'a été lancé.

Les revues en cours ont été **annulées volontairement** (limite d'usage) : re-revue D @ `9651c55` et revue B+C @ `e802e92`. Elles sont à relancer en tâches de revue **neuves** à la reprise.

## Tableau de suivi

| Sujet | Branche | SHA connu | Tests (rapportés par l'auteur) | Revue | Intégration |
|---|---|---|---|---|---|
| P1 A — données ignorées dans un worktree | `fix/worktree-data-safety` | `52bb0e5` (+ 2ᵉ tour en cours) | 15 tests `tests/test_worktree_ignored.py` ; suite 300 OK, 10 skipped | **Changements requis** (voir A ci-dessous) ; 2ᵉ tour envoyé à l'auteur | non |
| P1 B — pins perdus pendant fresh | `fix/version-policy-context` | `e802e92` | 28 tests `tests/test_version_policy_context.py` (B+C) ; suite 313 OK, 10 skipped | **à faire** (revue annulée) | non |
| P1 C — alias nvm en chaîne | même branche | `e802e92` | idem | **à faire** | non |
| P1 D — rollback permanent qui écrase | `fix/permanent-rollback-safety` | `689174e` → `9651c55` | 15 tests `tests/test_permanent_rollback.py` ; suite 300 OK, 10 skipped | `689174e` approuvé avec 6 points ; `9651c55` les corrige — **re-revue à faire** | non |
| Exig. 1 — runtimes Codex (supersession) | `fix/runtime-supersession` | en cours | — | à faire | non |
| Exig. 2 — dépendances livrées | `fix/shipped-deps-exclusion` | en cours | — | à faire | non |
| Exig. 3 — sessions de projet renommé | `fix/session-rename-uncertainty` | en cours | — | à faire | non |
| Exig. 4–6 + TUI risk groups | `fix/journal-undo-refusal` (créée depuis `9651c55`) | en cours | — | à faire | non |
| TUI (défilement, messages Corbeille, octets déplacés, instructions U) | dans `21ce749` | — | revue baseline : cohérent sauf listes de groupes à risque (traité dans `fix/journal-undo-refusal`) | faite (baseline) | déjà dans main |

Les SHA des branches « en cours » se lisent avec `git log --oneline -3 <branche>` ; chaque agent écrit son rapport final dans son thread.

Branches de preuve des reviewers (locales, à ne pas intégrer) : `review/opus-baseline` @ `4c39f2d` (sondes p1a…p6g), `review/rollback-689174e` @ `0d89147`, `review/worktree-52bb0e5` @ `f1e9315`, `t3/review-safety-fixes`.

## Constat de validation

- Sur `21ce749`, la suite complète est **285 tests OK, 10 skipped** (pas 2) : 8 `test_native_walk` (helper natif non compilé) + 2 `test_index_store.NativeRecovery` (`SOJI_TEST_NATIVE` absent). Les worktrees n'ont pas le helper natif : les tests natifs restent à lancer à l'intégration.
- J'ai moi-même relancé sur `689174e` : `tests.test_permanent_rollback` 8/8 OK, suite 293 OK, 10 skipped. Le reste des chiffres sont des rapports d'agents.
- Test dépendant de l'emplacement : `test_advanced.AdvancedRules.test_session_parts_and_memory_exclusion` échoue si le repo est copié sous `/private/tmp` (aussi sur `21ce749`).

## Détails par bug

### P1 A — `fix/worktree-data-safety`
`52bb0e5` : inventaire `git ls-files -z --others --ignored --exclude-standard --directory`, liste blanche (`node_modules`, `__pycache__`, caches pytest/mypy/ruff, `.DS_Store`, `*.pyc/.pyo`), échec fermé, ré-inspection dans `tool_action`, jamais `--force`. Repro d'origine corrigé.

Revue (changements requis), toujours suppression de données uniques sélectionnée dans les 3 modes :
1. P1 — un dossier au nom jetable dont tout le contenu est ignoré est excusé même s'il n'est pas ignoré lui-même (`__pycache__/important.db`, `node_modules/.env`, `node_modules/app.sqlite`).
2. P1 — dépôts Git imbriqués dans `node_modules` ignoré supprimés avec commits non poussés.
3. P1 — modifications de fichiers assume-unchanged / skip-worktree invisibles et perdues (préexistant).
4. P2 — variables `GIT_*` héritées ; sortie indécodable qui plante ; course entre ré-inspection et suppression (piste `git worktree move` vers un nom de staging).

2ᵉ tour demandé à l'auteur : dossier jetable seulement s'il est lui-même ignoré + parcours borné + aucun `.git` ; `git ls-files -v` ; retirer `GIT_*` ; décodage → non vérifié.

### P1 B+C — `fix/version-policy-context` @ `e802e92`
B : `fresh` fixe `pin_roots=plan['roots']`, `pin_live=True` → redécouverte live des pins sur toutes les racines du plan ; découverte incomplète → hold. C : `NvmAliases` borné (16 sauts, cycles, pas de traversée ni symlink, UTF-8 strict) ; incertitude → hold de toute la famille nvm. Repro : alias default et nouveau pin refusés.

Points à trancher en revue : un dossier illisible (ex. `~/.Trash` sans Full Disk Access) bloque toutes les familles pinnées ; anciens plans sans `roots` ; caches `batch['catalog']`/marqueurs ; coût d'un walk complet par item. Ouvert hors périmètre : autres marqueurs `keepVersionPointedToBy` (`~/.rbenv/version`, codex/claude/cursor/copilot) restent permissifs.

### P1 D — `fix/permanent-rollback-safety` @ `9651c55`
`platform.rename_exclusive` (`renameatx_np` + `RENAME_EXCL`, vérifié dans le SDK), sans repli ; `rollback_staged` garde les deux objets en conflit ; staging aussi exclusif ; objet substitué remis en place (`restored-other-identity`) ; `soji journal` affiche « staged copy kept for manual review » ; scanner bloque tout `.soji-removing-*` ; journal en panne → `journalError`.

À vérifier en re-revue : changement de comportement O-1 (suppression terminée dont l'écriture finale du journal échoue reste `done` + `journalError`, aussi pour Corbeille/tool-action) ; lignes non construites via `classify()` qui échapperaient au hold `.soji-removing-*`.

### Exigences de la baseline Opus (revue indépendante sur `21ce749`)
Fonctionne : atomicité runtime + refus fresh des sous-chemins, plancher 24 h sessions, chemins du cahier des charges exclus, caches dédiés proposés, journal mode/version/règle, app propriétaire active protège son cache.

Lacunes démontrées (sondes dans `review/opus-baseline` @ `4c39f2d`) :
- Exig. 1 (P1) : primaire absent, `runtime.json` absent, et l'hypothèse « version du primaire = install en usage » (fausse dans l'incident : L2Mqle 26.1007 vs primaire 26.1105) ; P2 `running_inside` sans realpath.
- Exig. 2 (P1) : globals bun/yarn, Mason, plugins nvim lazy, `~/.config/coc` quand `~/.config` est un dépôt dotfiles ; P2 manifeste annulé par VCS d'un parent.
- Exig. 3 (P2) : projet déplacé sous un autre parent / projet non-Git renommé jugé « disparu ».
- Exig. 4 (P2) : ligne nominée par un agent journalisée sans source/raison.
- Exig. 5 (P2) : objet remplacé dans la Corbeille annoncé récupérable ; Corbeille illisible annoncée vidée ; session composée partielle.
- Exig. 6 (P2) : « Contents changed » non mémorisé ; mémoire par chemin exact ; dépendance à des chaînes d'erreur ; échec silencieux de la source native des apps.
- TUI (P2) : `RISK_GROUPS` (TUI) ≠ `HIGH_RISK_GROUPS` (moteur).

## Reprise : ordre recommandé

1. Lire le rapport final de chaque agent en cours (threads T3 : `fix/worktree-data-safety` 2ᵉ tour, `fix/runtime-supersession`, `fix/shipped-deps-exclusion`, `fix/session-rename-uncertainty`, `fix/journal-undo-refusal`), contrôler diff + tests avant/après.
2. Relancer des revues **neuves et indépendantes** : D @ `9651c55`, B+C @ `e802e92`, A 2ᵉ tour, puis chaque branche baseline.
3. Intégrateur (agent) : ordre proposé D → journal-undo-refusal (bâtie sur D) → A → B+C → runtime → shipped-deps → session-rename ; conflits attendus dans `cleanup.py`, `specialized.py`, `engine.py`, `tests/corpus*.py` ; jamais ours/theirs arbitraire.
4. Revue transversale du résultat intégré (fresh vs scan complet, caches/TTL, jugements agents, index réutilisé, actions natives, racine/sous-chemin).
5. Sur le SHA intégré : `python3 -m unittest discover -s tests -q`, `git diff --check`, tests natifs avec helper compilé dans un emplacement jetable ; mise à jour de `docs/audit-2026-11-08.md` et `NEXT_STEPS.md` (état actuel par bug, SHA, limites).

## Décision de sécurité provisoire

**Ne pas utiliser Sōji pour un nettoyage réel**, quel que soit le mode, y compris careful : sur `main` (`21ce749`) les quatre P1 A–D et les lacunes P1 runtimes/dépendances livrées sont toujours présents, et aucune correction n'est intégrée ni revue jusqu'au bout. L'application installée n'est pas réparée par ces branches.
