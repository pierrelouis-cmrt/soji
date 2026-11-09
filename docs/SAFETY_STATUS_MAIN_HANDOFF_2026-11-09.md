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
