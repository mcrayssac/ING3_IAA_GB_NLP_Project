# BoxBox - Annexe d’exécution

[Retour à la roadmap](roadmap-cible.md). À consulter lors du démarrage d’une tâche ; les jalons et décisions de pilotage restent dans la roadmap.

Cette annexe conserve les détails utiles de la cible fournie. Les chemins sont des fichiers proposés dans le dépôt du projet, pas des fichiers présents dans ce dossier. Les commandes applicatives restent à fixer en M1.2. Toutes les validations humaines sont à réaliser.

## Workflow commun
### Une itération, de la base validée à la publication humaine

1. **Préparer.** Un humain choisit l’itération et renseigne AGENTS.md local. Vérifier dépôt, modifications préexistantes et prérequis validés/intégrés ; noter référence et SHA de départ. Créer/utiliser la branche exacte de la fiche, jamais `main` ; vérifier une branche existante sans la recréer de force.
2. **Implémenter.** Une session Codex traite uniquement la fiche et ses vérifications ; signaler tout dépassement du découpage prévu. Laisser les changements non commités, sans remiser, écraser ou supprimer le travail existant.
3. **Reviewer.** Une autre session Codex inspecte tous les changements depuis la base (commits éventuels, index, modifications locales et nouveaux fichiers), dans **le même répertoire et sur la même branche**. Un autre clone ne reçoit pas automatiquement ce travail.
4. **Valider humainement.** Le responsable réalise les tests de la fiche ; le relecteur distinct examine résultats et points sensibles. Corriger les blocages, relancer les vérifications concernées et une review si nécessaire. La review Codex ne vaut pas validation d’équipe.
5. **Intégrer humainement.** L’équipe valide et réalise elle-même `git add`, commit, push, éventuelle PR et fusion avant tout travail dépendant. Codex ne publie pas, ne réécrit pas l’historique et ne modifie pas l’identité Git.

**Suivi commun :** prévue → en cours → implémentée à revoir → validée par l’équipe → intégrée ; état « bloquée » si nécessaire. Chaque transition consigne résultats réussis/échoués/non exécutés et raisons, date réelle, responsable/relecteur et preuve d’intégration. Une case cochée ou un commit ne suffit pas. À chaque fin de jalon, actualiser roadmap, README et point rouge du diagramme historique dans une intervention autorisée ; ses anciennes dates ne font plus autorité.

### Parallélisme et fichiers communs

Chaque personne travaille dans son propre clone ou répertoire de travail séparé ; jamais de changements de branches concurrents dans un répertoire sale. Sa session de review réutilise exactement ce répertoire. L’équipe organise la transmission explicite d’un répertoire si nécessaire, nouveaux fichiers compris, et garde les identités réelles.

Les possibilités de travail simultané sont visibles dans la [séquence des dépendances](roadmap-cible.md#enchaînement-et-calendrier). Pour les fichiers partagés : **Paul coordonne `agent.ipynb`**, Matthieu les scripts de données, Maxime les règles et analyses. M2.6 livre sa cellule UI séparément ; l’intégration au notebook suit M2.4 et doit être vérifiée (première intégration à confirmer, voir roadmap). Le fichier de dépendances est édité séquentiellement après accord ; roadmap/README/diagramme sont consolidés après intégration. Preuves, commandes et tests font partie de chaque itération.

### Installer AGENTS.md dans chaque clone

Vérifier d’abord son existence, son contenu et `git ls-files -- AGENTS.md`. S’il est suivi, **ne pas l’éditer ou le désindexer automatiquement** : fournir la proposition séparément pour arbitrage, car le caractère strictement local serait incompatible. Sinon créer/compléter prudemment la version locale, en préservant ses consignes compatibles.

Résoudre le chemin avec `git rev-parse --git-path info/exclude`, puis ajouter une seule ligne `/AGENTS.md` si absente. Ne pas modifier `.gitignore`. Vérifier `git check-ignore -v AGENTS.md` et `git ls-files -- AGENTS.md` (aucune sortie pour ce dernier). Le fichier local et son exclusion doivent être installés **séparément dans les autres clones** ; ne pas compter sur un push. Les worktrees peuvent partager des métadonnées Git : vérifier le chemin réellement retourné et la portée de l’exclusion. La section de session reste à renseigner tant qu’aucune implémentation n’est demandée.


## Fiches de réalisation

I = implémentation, tests, corrections ordinaires et préparation de l’intégration ; R = review humaine et vérification. Un point représente environ 30–60 minutes d’attention humaine ; attente machine en supplément. Les dépendances et responsables sont centralisés dans la roadmap.

<a id="m1-1"></a>

### M1.1 - Contrat des cartes et politique de décision

**Branche :** `feat/m1-1-race-card-policy`. **I/R :** I 3 + R 0.5.

**Tâches ordonnées**

1. Relire le périmètre et fixer les champs (course/tour/voiture, pneus/âge, écarts, statut de piste, pit loss) et les valeurs manquantes sans inventer de seuil présenté comme une vérité F1.
2. Écrire une politique déterministe, ses limites, la distinction entre champ absent bloquant et champ absent sans effet, et un petit oracle de référence.
3. Définir l’interface commune carte + historique + message → réponse en deux lignes ; fixer la remise à zéro et le changement de carte.
4. Rédiger cinq conversations attendues et quelques cartes synthétiques explicitement identifiées comme fixtures ; faire valider les hypothèses.


**Modules/fichiers :** Existants à lire : README.md, présente roadmap. Proposés : docs/race-card-policy.md, src/boxbox/policy.py, tests/test_policy.py, tests/fixtures/cards.json.


**Critères d’acceptation :** Chaque classe de décision possède un exemple calculable ; le manque d’un champ non nécessaire ne force pas NO CALL ; aucune valeur absente n’est inventée ; cinq conversations et exclusions explicites sont disponibles.


**Tests humains**

- [ ] Précondition : contrat et fixtures ouverts. Recalculer à la main un BOX et un STAY OUT → même décision et justification fondée sur la carte.
- [ ] Retirer un champ indispensable puis un champ sans influence → NO CALL dans le premier cas seulement.
- [ ] Lire les cinq conversations, dont un suivi et une demande de pari/live → rôle conservé et refus cohérent.


**Contrôles :** Prévoir tests déterministes de seuils, champs absents, carte hors périmètre et format exact. Lanceur à fixer en M1.2.

**Points bloquants / review :** Review des seuils et de la causalité temporelle. Bloquants : règle contradictoire, champ futur requis, oracle confondu avec vérité stratégique, format ou contrat ambigu.

<a id="m1-2"></a>

### M1.2 - Modèle compact, environnement et observation pédagogique

**Branche :** `feat/m1-2-model-observation`. **I/R :** I 3 + R 0.5.

**Tâches ordonnées**

1. Constater CPU/GPU/mémoire et accès disponibles ; retenir un modèle adapté à l’anglais, documenter licence, révision et versions réellement compatibles sans achat implicite.
2. Créer la première section installation/observation de agent.ipynb ; montrer IDs de tokens, forme des logits, softmax et effets argmax/température/top-k ou top-p.
3. Relier les sorties aux embeddings, à l’attention causale et à l’unembedding ; justifier les paramètres de génération et la limite de contexte.
4. Faire quelques pas d’adaptation sur fixtures jetables, vérifier le gel de la base et le rechargement ; enregistrer temps/mémoire puis définir les commandes de tests et d’exécution effectives dans README.txt.


**Modules/fichiers :** Existants : aucun environnement applicatif. Proposés : agent.ipynb, README.txt, fichier de dépendances choisi et vérifié dans cette itération, src/boxbox/model.py, tests/test_model_contract.py.


**Critères d’acceptation :** Cellules d’observation exécutées et commentées ; distribution normalisée ; modèle/tokenizer identifiés ; essai d’adaptation rechargeable ; faisabilité matérielle et commandes reproductibles enregistrées.


**Tests humains**

- [ ] Précondition : environnement installé suivant le guide. Exécuter l’exemple court → sorties lisibles et dimensions expliquées.
- [ ] Comparer génération déterministe et échantillonnée → effets décrits sans promettre une différence à chaque tirage.
- [ ] Charger l’adaptateur jetable → génération possible, aucune preuve de performance revendiquée.


**Contrôles :** Assertions dans le notebook sur dimensions, somme softmax et paramètres entraînables ; smoke test génération et rechargement. Commandes précises à déterminer ici, puis les inscrire avec leur résultat ; ne pas présenter le Python système comme environnement du projet.

**Points bloquants / review :** Bloquants : modèle trop lourd/inaccessible, absence d’observations P2, base entraînée, licence incompatible avec la remise ou durée de calcul incompatible avec le gel du 20/10.

<a id="m2-1"></a>

### M2.1 - Extraction historique et partitions par course

**Branche :** `feat/m2-1-race-splits`. **I/R :** I 3 + R 0.5.

**Tâches ordonnées**

1. Identifier les courses accessibles et les champs réellement disponibles ; définir le traitement des tours invalides et des données absentes.
2. Figer les quatre listes de courses, leurs identifiants et la graine avant la génération ; vérifier assez de courses pour l’évaluation groupée.
3. Produire des cartes conformes à M1.1 ; calculer les écarts et pit loss uniquement à partir des informations disponibles avant le tour évalué.
4. Conserver paramètres de reconstruction, versions et empreintes ; documenter cache et échecs réseau sans publier les fichiers bruts de chronométrage.


**Modules/fichiers :** Proposés : scripts/rebuild_data.py, src/boxbox/data.py, data/splits.json, docs/data-protocol.md, tests/test_data.py. Contrat proposé en M1.1 réutilisé. Dépendances communes à coordonner avec M1.2 ; pas d’édition concurrente du même fichier.


**Critères d’acceptation :** Au moins une carte réelle reproductible, provenance traçable, partitions sans course commune, pit loss sans connaissance future, absence de dépendance obligatoire à OpenF1.


**Tests humains**

- [ ] Précondition : cache ou accès FastF1 utilisable. Reconstruire deux fois une carte → mêmes champs avec mêmes paramètres et sources.
- [ ] Examiner ses tours sources → aucun tour futur utilisé.
- [ ] Simuler une absence réseau ou un champ absent → erreur explicite ou valeur manquante tracée, aucune invention.


**Contrôles :** Tests à créer : disjonction des courses, unités/champs, borne temporelle, fixture de donnée manquante et erreur de récupération. Commande via lanceur défini en M1.2 une fois intégré ; sinon assertion Python ciblée à documenter.

**Points bloquants / review :** Bloquants : partitions après génération, fuite entre courses ou dans le temps, téléchargement irrécupérable, données brutes redistribuées sans décision explicite sur leurs droits.

<a id="m2-2"></a>

### M2.2 - Corpus A/B et jeux d’évaluation séparés

**Branche :** `feat/m2-2-dialogue-corpora`. **I/R :** I 4 + R 1.

**Tâches ordonnées**

1. Générer après les partitions les dialogues anglais conformes à la politique ; A utilise des cartes complètes, B conserve exactement 340 exemples de A et remplace 60 exemples par une variante à champ indispensable absent.
2. Préparer validation, au moins 20 requêtes de mini-test non entraînées et environ 200 cas finaux distincts ; couvrir cartes complètes, champ indispensable absent, champ non nécessaire absent, suivis et hors périmètre.
3. Vérifier manuellement qualité, diversité, labels et absence de données personnelles sensibles ; tenir le registre des corrections et du nombre effectivement lu.
4. Geler versions/empreintes et procédure de reconstruction ; isoler le jeu final et ne pas en produire de réponses avant M4.2.


**Modules/fichiers :** Existants : aucun corpus. Proposés/issus de M2.1 : scripts/rebuild_data.py, data/splits.json. Proposés : data/manifests/, docs/data-quality.md, tests/test_corpora.py ; dialogues générés locaux, mode de remise via script.


**Critères d’acceptation :** 400/400 visés, 340 exemples partagés et 60 remplacements traçables ; lectures manuelles enregistrées ; partitions disjointes ; ≥20 mini-tests ; final avec les cinq catégories ; reconstruction documentée. Toute réduction demande un arbitrage visible.


**Tests humains**

- [ ] Précondition : corpus généré et règles acceptées. Lire les 400 exemples de A et les 60 remplacements de B, vérifier qualité/anglais/justification et consigner anomalies → corrections puis contrôles relancés.
- [ ] Le relecteur contrôle les cas sensibles et un échantillon des autres ; aucune donnée personnelle sensible conservée.
- [ ] Vérifier manifestes et accès au test final sans utiliser ses réponses pour régler le modèle → séparation préservée.


**Contrôles :** Tests à créer : comptes, ratio 85/15, identifiants et courses disjoints, schéma messages/format, variants effectivement insuffisants, déterminisme sur fixture. Commande à confirmer via M1.2 ; aucun score final calculé.

**Points bloquants / review :** Bloquants : fuite de course, labels incohérents, lecture manuelle non faite, remplacements B qui permettent encore un call, test final utilisé pour sélectionner. Si le volume dépasse le créneau, replanifier explicitement sans supprimer la vérification humaine.

<a id="m2-3"></a>

### M2.3 - Baseline conversationnelle et choix du prompt

**Branche :** `feat/m2-3-conversation-baseline`. **I/R :** I 3 + R 0.5.

**Tâches ordonnées**

1. Implémenter le contrat de M1.1 avec message système et format conversationnel attendu par le tokenizer.
2. Borner l’historique selon la fenêtre de contexte en préservant carte et instructions ; expliciter la stratégie de troncature.
3. Comparer deux prompts ou zero-shot/few-shot sur la même validation et avec paramètres contrôlés ; choisir selon critères consignés.
4. Sauvegarder prompts, configuration, réponses baseline et exemples de suivi/refus ; exposer un appel partagé à l’interface et à l’évaluation.


**Modules/fichiers :** Proposés : src/boxbox/conversation.py, configs/baseline.json, results/baseline-validation.jsonl, tests/test_conversation.py ; compléter agent.ipynb introduit en M1.2.


**Critères d’acceptation :** Deux variantes comparées sur validation, choix motivé, outputs conservés ; historique borné ; suivis et refus traités ; chaque réponse vise CALL/WHY et les erreurs du modèle sont comptées, pas masquées.


**Tests humains**

- [ ] Précondition : modèle chargé et carte valide. Poser une question puis un suivi → contexte conservé et explication liée à la carte.
- [ ] Accumuler des tours jusqu’à la borne → pas de dépassement, politique de troncature observable.
- [ ] Envoyer demande hors périmètre et carte insuffisante → refus/NO CALL attendu ; tout échec enregistré comme résultat baseline.


**Contrôles :** Tests à créer sur assemblage/template, borne de contexte, remise à zéro et sérialisation ; smoke test du modèle réel. Utiliser les commandes confirmées en M1.2, enregistrer les commandes exactes de cette itération.

**Points bloquants / review :** Bloquants techniques : absence de template natif, fuite de test, historique incontrôlé, sorties perdues. Une mauvaise qualité de baseline est un résultat expérimental, pas une raison de falsifier ou filtrer ses réponses.

<a id="m2-4"></a>

### M2.4 - Entraînement et rechargement de l’adaptateur A

**Branche :** `feat/m2-4-adapter-a`. **I/R :** I 4 + R 1.

**Tâches ordonnées**

1. Fixer modèle/révision, quantification éventuelle, rang LoRA, taux d’apprentissage, lots, époques, longueur maximale, graine et critère d’arrêt.
2. Vérifier les paramètres entraînables puis entraîner uniquement l’adaptateur sur A ; conserver pertes train/validation et incidents.
3. Choisir et sauvegarder le meilleur checkpoint selon validation ; justifier l’arrêt même si les gains sont faibles.
4. Recharger depuis le disque dans un processus propre et sauvegarder les réponses de validation avec même protocole que la baseline.


**Modules/fichiers :** Proposés : src/boxbox/training.py, configs/train-a.json, artifacts/adapter-a/ (local ou lien stable), results/train-a/ ; compléter agent.ipynb ; tests/test_training_contract.py.


**Critères d’acceptation :** Base gelée, seul adaptateur entraîné ; hyperparamètres et courbes présents ; sélection et arrêt justifiés ; artefact rechargeable identifié. Un gain positif n’est pas requis.


**Tests humains**

- [ ] Précondition : corpus A accepté et environnement M1.2. Examiner les courbes et le checkpoint sélectionné → sélection basée sur validation.
- [ ] Recharger A puis poser les mêmes questions de validation que la baseline → réponses conservées, pas de mélange des versions.
- [ ] Consulter temps/mémoire/logs → estimation de durée de B mise à jour avant son lancement.


**Contrôles :** Contrôles des paramètres gelés/entraînables, longueurs et masquage retenu, pertes finies, sauvegarde/rechargement ; exécuter les tests rapides avant le run coûteux. Commande d’entraînement à définir et consigner à cette étape.

**Points bloquants / review :** Bloquants : entraînement de la base, perte invalide non expliquée, meilleur checkpoint absent, train/test mélangés ou rechargement impossible.

<a id="m2-5"></a>

### M2.5 - Mini-test comparatif du premier prototype

**Branche :** `feat/m2-5-prototype-mini-test`. **I/R :** I 3 + R 0.5.

**Tâches ordonnées**

1. Vérifier séparation et versions puis exécuter baseline et A sur les mêmes ≥20 requêtes.
2. Appliquer la grille M4.1, conserver réponses brutes et produire tableau synthétique.
3. Commenter au moins cinq cas, dont suivi/hors périmètre et invention éventuelle ; signaler les échecs qui contredisent l’hypothèse.


**Modules/fichiers :** Proposés : results/mini-test/, docs/mini-test-analysis.md ; utiliser le module d’évaluation de M4.1, sans modification concurrente de agent.ipynb.


**Critères d’acceptation :** ≥20 requêtes non entraînées, cinq axes de grille et ≥5 commentaires ; baseline et A clairement identifiées ; aucune suppression des cas défavorables.


**Tests humains**

- [ ] Précondition : grille figée avant réponses. Lire les réponses en paire → notes justifiées et critères appliqués de façon identique.
- [ ] Vérifier au moins cinq commentaires contre les cartes sources → aucune conclusion sans preuve.


**Contrôles :** Contrôler nombre de cas, appariement IDs et intégrité des versions ; exécuter le runner défini en M4.1. Commande exacte encore à déterminer lors de M4.1.

**Points bloquants / review :** Bloquants : moins de 20 requêtes, grille après résultats, comparaison non appariée ou absence de baseline. Les scores faibles doivent être conservés.

<a id="m2-6"></a>

### M2.6 - Interface Gradio avec carte et historique

**Branche :** `feat/m2-6-gradio-chat`. **I/R :** I 3 + R 0.5.

**Tâches ordonnées**

1. Construire la vue carte, zone de conversation, champ message, reset et présentation des limites.
2. Relier à la fonction M2.3 ; vider l’historique lors du changement de carte et isoler l’état des conversations.
3. Tester avec baseline réelle et adaptateur factice conforme au contrat ; fournir la cellule de lancement prête à intégrer au notebook en M5.1.


**Modules/fichiers :** Proposés : src/boxbox/ui.py, docs/ui-launch-cell.md, tests/test_ui_state.py. agent.ipynb est la cible finale ; pour éviter le conflit avec M2.4, ne pas l’éditer en parallèle, livrer la cellule puis l’intégrer humainement après M2.4.


**Critères d’acceptation :** Parcours complet avec baseline, reset réellement vide, changement de carte sans ancien contexte, rôle/limites lisibles ; lancement depuis agent.ipynb vérifié après intégration, avant fermeture du jalon 2.


**Tests humains**

- [ ] Précondition : notebook et dépendances disponibles. Lancer la cellule → interface accessible, rôle et limites affichés.
- [ ] Choisir carte, poser question et suivi → carte/historique transmis au moteur.
- [ ] Réinitialiser puis changer de carte → aucun message ancien ; provoquer erreur moteur → message compréhensible sans casser l’interface.


**Contrôles :** Tests de callbacks/reset/changement de carte, erreurs d’inférence ; smoke test lancement à définir selon versions Gradio confirmées en M1.2. Test navigateur humain indispensable.

**Points bloquants / review :** Bloquants : lancement hors notebook uniquement, reset visuel sans effacement réel, état partagé entre conversations, carte non transmise ou dépendance obligatoire à l’adaptateur non disponible.

<a id="m3-1"></a>

### M3.1 - Entraînement contrôlé de l’adaptateur B

**Branche :** `feat/m3-1-adapter-b`. **I/R :** I 2 + R 0.5.

**Tâches ordonnées**

1. Comparer manifestes : mêmes 340 exemples et 60 substitutions, même base, budget, graine et réglages que A.
2. Lancer B, journaliser pertes et sélection sur validation selon le même critère.
3. Recharger B et produire les réponses de validation et du mini-test nécessaires à M3.2, sans toucher au final.


**Modules/fichiers :** Existants à ce stade : src/boxbox/training.py. Proposés : configs/train-b.json, artifacts/adapter-b/, results/train-b/, results/b-validation-mini-test/.


**Critères d’acceptation :** Différence A/B limitée à l’intervention annoncée ; réglages identiques ; B rechargeable et pertes conservées ; écarts ou incidents explicités.


**Tests humains**

- [ ] Précondition : A accepté, corpus gelés. Comparer les fiches de run → aucun facteur de confusion non déclaré.
- [ ] Recharger B et examiner une carte incomplète ainsi qu’une carte complète → réponses archivées, y compris refus abusifs.


**Contrôles :** Comparer automatiquement configs et empreintes des parties communes ; réutiliser tests entraînement/rechargement de M2.4 et contrôles d’IDs de M4.1. Commande exacte héritée de M2.4, non disponible dans le dépôt initial.

**Points bloquants / review :** Bloquants : mêmes poids A utilisés par erreur, réglages non comparables non signalés, final consulté, checkpoint inaccessible. Un résultat négatif reste publiable.

<a id="m3-2"></a>

### M3.2 - Analyse intermédiaire et gel des versions

**Branche :** `docs/m3-2-analysis-freeze`. **I/R :** I 1 + R 0.5.

**Tâches ordonnées**

1. Comparer A/B sur validation et mini-test, y compris appels injustifiés sur cartes insuffisantes et abstentions sur cartes suffisantes.
2. Conserver les résultats contraires à l’hypothèse et constater explicitement la stabilité ou l’incertitude.
3. Geler toutes les versions évaluées et leurs paramètres ; vérifier que les sept étapes du prototype disposent de leurs éléments.
4. Fermer l’accès aux nouvelles expériences après le gel ; toute correction affectant les sorties invalide le gel et exige un arbitrage documenté avant une nouvelle évaluation.


**Modules/fichiers :** Proposés : docs/interim-analysis.md, results/freeze-manifest.json ; présente roadmap pour statut et preuves. Le diagramme historique reste inchangé.


**Critères d’acceptation :** Analyse pré-finale disponible, empreintes identifiables, décision humaine horodatée et absence d’expérience nouvelle après le gel du 20/10.


**Tests humains**

- [ ] Précondition : mini-test, UI et B acceptés. Ouvrir les résultats et vérifier chaque version → références rechargeables.
- [ ] Relire conclusions → incertitude et résultats négatifs visibles ; valider le gel avant de transmettre au responsable de M4.2.


**Contrôles :** Vérifier existence/empreintes des artefacts et couverture du manifeste ; aucun nouveau score final. Commande de contrôle à fournir avec le manifeste.

**Points bloquants / review :** Bloquants : gel sans artefact, versions ambiguës, final déjà exploité. Le 14/10 était une ancienne date prévue, jamais une réalisation prouvée.

<a id="m4-1"></a>

### M4.1 - Grille d’évaluation et calculs sur fixtures

**Branche :** `feat/m4-1-evaluation-protocol`. **I/R :** I 3 + R 0.5.

**Tâches ordonnées**

1. Définir avant résultats les critères pertinence/correction, rôle/format, historique, hors périmètre et informations inventées/non vérifiables, avec ancres explicites 0/1/2.
2. Distinguer mesures automatiques de format/politique et jugement humain ; définir abstention justifiée et refus excessif.
3. Implémenter appariement par cas, tableau par catégorie et bootstrap par course avec graine/nombre de tirages documentés ; fixer le niveau d’intervalle avant les résultats.
4. Prévoir un lot de 40 cas pour notation humaine de chaque version évaluée (120 réponses si baseline/A/B), pseudonymes aléatoires, clé séparée et limites de l’aveugle ; tester uniquement sur fixtures.


**Modules/fichiers :** Proposés : docs/evaluation-protocol.md, src/boxbox/evaluation.py, tests/test_evaluation.py ; utiliser les identifiants du manifeste de M2.2.


**Critères d’acceptation :** Grille définie à l’avance ; cinq dimensions couvertes ; 40 cas et échelle explicite ; bootstrap rééchantillonne des courses entières ; cas incomplets suffisants et insuffisants séparés ; test final fermé.


**Tests humains**

- [ ] Précondition : uniquement fixtures factices. Noter deux réponses exemples → application compréhensible des ancres.
- [ ] Comparer calcul manuel et tableau sur petit lot → même appariement et dénominateurs.
- [ ] Vérifier que les fichiers destinés au notateur ne révèlent pas la version → aveugle possible ou limite déclarée.


**Contrôles :** Tests à créer avec résultats connus : versions identiques → différence nulle, IDs désalignés rejetés, course conservée en bloc, catégorie vide signalée, un seul groupe → IC non interprétable. Lanceur M1.2 ; runner final à documenter ici.

**Points bloquants / review :** Bloquants : grille ajustée après résultats, bootstrap par ligne présenté comme groupé, erreur d’appariement ou notation automatique présentée comme humaine.

<a id="m4-2"></a>

### M4.2 - Évaluation finale fermée et analyse des erreurs

**Branche :** `feat/m4-2-final-evaluation`. **I/R :** I 3 + R 1.

**Tâches ordonnées**

1. Contrôler le manifeste de gel puis ouvrir le final et scorer chaque version figée une seule fois ; sauvegarder réponses et incidents.
2. Produire tableaux globaux/par catégorie, différences et IC groupés ; signaler le manque éventuel de courses et l’incertitude.
3. Le responsable note les 40 cas par version en aveugle si possible ; le relecteur examine les points sensibles et divergences, avec notes justifiées.
4. Commenter au moins cinq réussites/erreurs et tous types de limites significatives, dont résultats contraires à l’hypothèse ; conserver les sorties brutes.


**Modules/fichiers :** Proposés : results/final/, docs/final-analysis.md ; module M4.1 réutilisé. Tables prêtes pour notebook et rapport.


**Critères d’acceptation :** Final distinct du mini-test et non entraîné ; environ 200 cas, cinq catégories, 40 cas humains/version et cinq commentaires ; baseline incluse ; IC et limites explicites ; aucune amélioration prétendue sans preuve.


**Tests humains**

- [ ] Précondition : gel validé et versions masquées. Noter les 40 cas/version en justifiant chaque axe → feuilles de notes traçables.
- [ ] Le relecteur confronte erreurs majeures aux cartes et aux règles → désaccords consignés et tranchés sans cacher de cas.
- [ ] Relire les cinq analyses et les intervalles → pas de confusion entre accord avec politique et optimalité réelle.


**Contrôles :** Exécuter runner M4.1 puis contrôles de couverture, unicité cas/version, empreintes, notes 0–2 et appariement. Commandes à reprendre du protocole accepté ; pas de répétition du run pour choisir un meilleur résultat.

**Points bloquants / review :** Bloquants : final ouvert avant gel, baseline absente, notes humaines inventées, erreurs exclues silencieusement, IC mal groupés. Une panne technique peut être reprise seulement avec journal explicite, sans réglage ni sélection opportuniste.

<a id="m5-1"></a>

### M5.1 - Notebook complet et exécution propre

**Branche :** `fix/m5-1-reproducible-notebook`. **I/R :** I 2 + R 0.5.

**Tâches ordonnées**

1. Intégrer les cellules d’interface et les tableaux/analyses ; vérifier la progression pédagogique et les explications anglaises.
2. Installer dans un environnement neuf, reconstruire les données selon le guide, recharger les adaptateurs et exécuter le notebook de bout en bout ; distinguer entraînement reproductible et rechargement documenté.
3. Conserver preuve de l’exécution, versions, durée, accès aux adaptateurs et instructions CPU/GPU réellement testées ; si relecture du final, réutiliser ses réponses figées plutôt que créer une nouvelle mesure.
4. Vérifier que le notebook remis contient sorties et pertes réelles de l’entraînement ; un mode rapide par rechargement ne remplace pas la preuve d’adaptation.


**Modules/fichiers :** Existants à ce stade : agent.ipynb, README.txt, modules, scripts et artefacts des itérations précédentes. Pas de nouveau framework.


**Critères d’acceptation :** Notebook exécuté sans cellule en erreur, ordre installation→interface, sorties réelles de toutes étapes ; lancement Gradio depuis notebook ; guide et artefacts accessibles ; reconstruction reproductible.


**Tests humains**

- [ ] Précondition : environnement neuf, guide seul et artefacts accessibles. Suivre README.txt → parcours complet avec sorties observables.
- [ ] Lancer Gradio avec A ou B puis message/suivi/reset → moteur adapté réellement utilisé.
- [ ] Comparer versions et résultats réutilisés au gel → aucune modification silencieuse après le test final.


**Contrôles :** Commandes d’installation/exécution exactes de M1.2 et du guide, tests ciblés d’intégration, contrôle structure JSON du notebook et absence de sorties d’erreur. Aucun lanceur notebook n’est confirmé au jour de l’audit.

**Points bloquants / review :** Bloquants : fichier non exécuté, dépendance cachée au poste d’auteur, lien inaccessible, manque de courbes ou interface non lancée depuis notebook. Coût machine de rerun à réserver après mesure en M1.2.

<a id="m5-2"></a>

### M5.2 - Rapport français de quatre pages

**Branche :** `docs/m5-2-report`. **I/R :** I 3 + R 0.5.

**Tâches ordonnées**

1. Rédiger les six thèmes obligatoires avec résultats finaux et une explication des règles/limites de BoxBox.
2. Inclure synthèse avant/après adaptation et recherche A/B, renvoyer au notebook pour détails et cinq cas commentés.
3. Exporter PDF, compter les pages hors annexes et contrôler visuellement tableaux, accents, lisibilité et cohérence des chiffres.


**Modules/fichiers :** Proposés : rapport.pdf et source éditable du rapport (format à choisir) ; lire docs/final-analysis.md et résultats figés.


**Critères d’acceptation :** ≤4 pages hors annexes clairement séparées, français, thèmes obligatoires présents ; chiffres traçables ; résultats négatifs et limites conservés.


**Tests humains**

- [ ] Précondition : PDF exporté. Lire chaque page à taille normale → aucun texte tronqué et tableaux lisibles.
- [ ] Contrôler cas d’usage/données/choix/comparaison/limites/améliorations → tous présents, pas de conclusion plus forte que les résultats.


**Contrôles :** Compter les pages avec un outil PDF disponible (pdfinfo a été exécuté dans cet audit sur le brief), comparer les valeurs au tableau final ; commande d’export à déterminer selon source choisie.

**Points bloquants / review :** Bloquants : dépassement de quatre pages hors annexes, thème obligatoire absent, chiffres non traçables ou confusion entre baseline/A et A/B.

<a id="m5-3"></a>

### M5.3 - Vidéo de présentation de trois minutes

**Branche :** `docs/m5-3-pitch-video`. **I/R :** I 2 + R 0.5.

**Tâches ordonnées**

1. Préparer un script court : besoin, carte, réponse/suivi/NO CALL, résultat et limite.
2. Enregistrer la démo avec données non sensibles, monter sobrement et exporter.
3. Vérifier durée, voix, lisibilité et accès au fichier avec le relecteur.


**Modules/fichiers :** Proposés : docs/pitch-script.md, livrable vidéo local ou lien durable (nom et format à fixer selon canal de rendu). Aucun outil vidéo n’est encore choisi.


**Critères d’acceptation :** Vidéo française de trois minutes visée, usage et limites visibles, fichier lisible et accessible ; chiffres cohérents avec rapport.


**Tests humains**

- [ ] Précondition : export final. Lire intégralement sur un second lecteur/poste → son compréhensible, texte visible et durée conforme.
- [ ] Comparer les fonctionnalités montrées et le rapport → aucune promesse non implémentée.


**Contrôles :** Contrôle technique durée/lecture via outil disponible à choisir, pas de suite de tests applicative nouvelle pour cette tâche.

**Points bloquants / review :** Bloquants pour cet engagement : fichier illisible, lien privé inaccessible, absence de démo ou contenu trompeur. Ne pas sacrifier un livrable obligatoire pour du montage supplémentaire.

<a id="m5-4"></a>

### M5.4 - Contrôle du paquet et préparation du rendu

**Branche :** `chore/m5-4-delivery-check`. **I/R :** I 1 + R 0.5.

**Tâches ordonnées**

1. Vérifier agent.ipynb exécuté, rapport.pdf, script reproductible/données autorisées, adaptateur ou lien stable, README.txt ; ajouter vidéo projet.
2. Tester depuis un contexte lecteur les liens et la reconstruction documentée, vérifier licences et absence de chronométrage brut distribué par erreur.
3. Faire signer la checklist par responsable/relecteur ; confirmer humainement canal et heure limite réelle, puis laisser un membre effectuer le dépôt et conserver le reçu.


**Modules/fichiers :** Existants à ce stade : livrables précédents. Proposé : docs/delivery-checklist.md. Le canal de dépôt n’est pas précisé dans le PDF et ne doit pas être inventé.


**Critères d’acceptation :** Cinq livrables accessibles sous les noms exigés, vidéo accessible, versions concordantes, aucun blocage ouvert. « Prêt à déposer » distinct de « déposé », ce dernier exige un reçu humain.


**Tests humains**

- [ ] Précondition : paquet local final. Ouvrir chaque livrable et suivre les liens depuis un accès lecteur → aucun fichier manquant ni authentification imprévue.
- [ ] Relecteur compare checklist aux trois pages du brief → couverture complète.
- [ ] Membre désigné par l’équipe dépose avant le soir et conserve preuve → statut déposé seulement après constat.


**Contrôles :** Contrôles de présence, empreintes et structure notebook/PDF ; liens testés en lecture. Commandes exactes à consigner dans checklist, sans nouvelle infrastructure de tests.

**Points bloquants / review :** Bloquants : livrable obligatoire absent, liens cassés, rapport trop long, notebook non exécuté ou divergences de versions. Réserver l’après-midi aux corrections et contrôles ; aucun dépôt automatique.

<a id="calendrier-detaille"></a>

## Calendrier détaillé

Scénario conditionnel, octobre 2026, heure de Paris. Une review comprend essais humains, corrections et intégration avant la tâche dépendante. Le 19, review de A en début de soirée, puis UI en fin de soirée.

| ID | Implémentation prévue | Review / intégration prévue |
|---|---|---|
| M1.1 | 16/10 après l’audit source | 16/10 fin de journée |
| M1.2 | 16/10 après l’audit source – fin de journée | 17/10 matin |
| M2.1 | 17/10 matin après M1.2 | 17/10 milieu de journée |
| M2.2 | 17/10 après-midi – 18/10 matin | 18/10 milieu de journée |
| M2.3 | 18/10 après-midi | 18/10 fin de journée |
| M2.4 | 19/10 matin – après-midi | 19/10 début de soirée |
| M2.5 | 20/10 matin | 20/10 milieu de journée |
| M2.6 | 19/10 matin – après-midi | 19/10 fin de soirée |
| M3.1 | 20/10 matin | 20/10 milieu de journée |
| M3.2 | 20/10 après-midi | 20/10 fin d’après-midi, avant ouverture du final |
| M4.1 | 18/10 après-midi | 18/10 fin de journée |
| M4.2 | 20/10 soirée après gel – 21/10 matin | 21/10 milieu de journée |
| M5.1 | 21/10 après-midi | 21/10 fin d’après-midi |
| M5.2 | 21/10 après-midi | 21/10 début de soirée |
| M5.3 | 21/10 soirée après review du rapport | 22/10 début de matinée |
| M5.4 | 22/10 matin après validation vidéo | 22/10 milieu de journée |

### Charge par personne, borne haute

| Personne | 16 après audit | 17 | 18 | 19 | 20 | 21 | 22 tâches + réserve | Total haut avec réserve |
|---|---|---|---|---|---|---|---|---|
| Maxime | 3 h | 0,5 h | 1 h | 0 h | 4,5 h | 6 h | 0 h + 2 h | 17 h |
| Paul | 3,5 h | 0 h | 4 h | 4,5 h | 2,5 h | 2,5 h | 0,5 h + 3 h | 20,5 h |
| Matthieu | 0 h | 5,5 h | 5 h | 4 h | 1,5 h | 2,5 h | 1,5 h + 3 h | 23 h |

Les 52,5 points se répartissent en 43 points I et 9,5 points R. Réserve : Maxime 2 h, Paul 3 h, Matthieu 3 h. Réestimer après les premiers runs et les lectures de corpus ; aucune disponibilité réelle n’est attestée.

<a id="referentiel"></a>

## Référentiel conservé

Transcription du référentiel de la cible, sans nouvel examen du PDF ou du README. P/L = obligations professeur rapportées par la source ; B = engagements du projet. Le conseil de 200–1 000 exemples ne constitue pas un seuil obligatoire.

| Code | Source | Exigence conservée |
|---|---|---|
| P1 | PDF p. 1, étape 1 | Utilisateur, rôle, demandes acceptées/refusées ou redirigées, périmètre étroit et cinq conversations attendues. |
| P2 | PDF p. 1, étape 2 | Transformer instructionnel compact adapté à langue/ressources ; tokenizer et modèle causal avec transformers ; IDs, forme logits, softmax du prochain token ; argmax, température et top-k ou top-p ; liens embeddings, attention causale et unembedding. |
| P3 | PDF p. 2, étape 3 | Baseline sans entraînement : système, format du tokenizer, historique borné, génération justifiée ; ≥2 prompts ou zero-shot/few-shot ; conserver les réponses de la meilleure configuration. |
| P4 | PDF p. 2, étape 4 | Dialogues représentatifs séparés train/validation/test ; qualité et absence de données personnelles sensibles vérifiées manuellement. 200–1 000 exemples courts est un ordre de grandeur conseillé, pas un seuil obligatoire. |
| P5 | PDF p. 2, étape 5 | LoRA ou QLoRA, base gelée, seuls adaptateurs entraînés ; base, quantification éventuelle, rang, taux d’apprentissage, lots, époques, longueur maximale ; pertes train/validation ; meilleur adaptateur validation et arrêt justifié. |
| P6 | PDF p. 2, étape 6 | ≥20 requêtes test non entraînées ; comparaison baseline/adaptation ; grille préalable : correction/pertinence, rôle/format, historique, hors périmètre, inventions ; tableau et ≥5 réussites/erreurs commentées. Évaluation humaine argumentée permise avec critères/échelle explicites. |
| P7 | PDF p. 2, étape 7 | Gradio lancé depuis notebook : conversation, saisie, reset de l’historique, présentation rôle/limites ; hébergement permanent non demandé. |
| L1 | PDF p. 3 | agent.ipynb exécuté, organisé de l’installation à l’interface. |
| L2 | PDF p. 3 | rapport.pdf ≤4 pages hors annexes ; cas d’usage, données, choix techniques, comparaison, limites et améliorations possibles. |
| L3 | PDF p. 3 | Données créées ou script reproductible permettant de les obtenir. |
| L4 | PDF p. 3 | Adaptateur LoRA ou lien stable de téléchargement. |
| L5 | PDF p. 3 | README.txt avec instructions d’exécution. |
| B1 | README, besoin et comportement | Créateurs de contenu/analystes F1 ; course historique, un tour, une voiture, piste sèche ; carte visible et suivis ; réponse exacte sur deux lignes : `CALL: BOX \| STAY OUT \| NO CALL`, puis `WHY: <one sentence in English, based on the race card>`. Ne pas inventer de valeur ; abstention si information nécessaire manquante. |
| B2 | README, périmètre/limites | Politique explicite, cohérence avec règles ≠ stratégie optimale réelle ; exclure live, simulation complète, optimisation multi-arrêts, météo prédictive, paris, radios d’équipe inventées et hébergement permanent. |
| B3 | README sources/licence ; cible §1 | FastF1 choisi le 26/09 ; pit loss calculé uniquement avec données disponibles avant le tour ; essai petit modèle et entraînement sur ordinateur d’équipe ou GPU cloud gratuit ; scripts de reconstruction plutôt que chronométrage brut partagé. Code/docs Apache-2.0, droits tiers et licence du modèle distincts ; usage académique non commercial ; projet non officiel sans affiliation F1. |
| B4 | Cible §2 | Partition par course AVANT dialogues : entraînement, validation, mini-test exploratoire, final fermé ; environ 400 dialogues relus ; A, pertes, meilleur checkpoint ; mini-test ≥20 et cinq cas commentés. |
| B5 | Cible §1 | Fixer règles/champs/hypothèses/seuils et répartir les rôles avec review croisée. |
| B6 | README recherche ; cible §3 | Comparer A cartes complètes à B : 400 exemples chacun, 85 % communs (340), 15 % remplacés (60) par cartes à champ nécessaire manquant et NO CALL ; mêmes réglages ; analyse sur validation/mini-test, abstention utile et refus excessifs ; publier résultats négatifs/incertains. |
| B7 | Cible §3–4 | Gel avant ouverture du final, une mesure par version figée ; environ 200 cas : complets, incomplets bloquants, incomplets suffisants, suivis, hors périmètre ; 40 cas humains, échelle 0–2, aveugle si possible ; différences appariées et IC rééchantillonnés par course ; ≥5 erreurs/réussites, y compris contre-hypothèse. |
| B8 | README langues ; cible §2/5/suivi | Carte et chat Gradio ; réexécution propre ; guide/script/lien vérifiés ; vidéo française de 3 minutes pour le public F1 ; langues définies dans la roadmap ; mise à jour roadmap, README et point rouge du diagramme à la fin des jalons. |
| B9 | Cible §3 ; README sources | Options uniquement après prototype et analyse : autre graine A/B si instable, sinon second modèle V2 ; aucun nouvel essai après gel. OpenF1 reste une contre-vérification facultative. |

### Couverture par les itérations

| Exigence source | Itérations / preuve attendue |
|---|---|
| P1 - définition et cinq conversations | M1.1, M2.2 ; contrat, cinq exemples et corpus |
| P2 - tokenizer, logits, softmax, génération, lien au cours | M1.2, M5.1 ; cellules commentées exécutées |
| P3 - baseline, format natif, historique, deux prompts | M2.3 ; configuration choisie sur validation et réponses conservées |
| P4 - séparation, qualité, absence de données sensibles | M2.1, M2.2 ; manifestes avant dialogues, contrôles automatiques et registre manuel |
| P5 - LoRA/QLoRA, base gelée, réglages, pertes, sélection/arrêt | M1.2, M2.4, M3.1 ; logs/courbes/checkpoints, rechargement |
| P6 - ≥20 tests, cinq axes, tableau, cinq cas | M4.1, M2.5, M4.2 ; grille préalable et tableaux baseline/A/B, notes argumentées |
| P7 - Gradio complet depuis notebook | M2.6, M5.1 ; parcours carte/message/suivi/reset et lancement constaté |
| L1 - agent.ipynb exécuté | M1.2, M2.3, M2.4, M5.1, M5.4 ; notebook final avec sorties et séquence complète |
| L2 - rapport.pdf ≤4 pages hors annexes et six thèmes | M5.2, M5.4 ; PDF compté/inspecté |
| L3 - données ou reconstruction | M2.1, M2.2, M5.1, M5.4 ; script et paramètres reproductibles |
| L4 - adaptateur ou lien stable | M2.4, M3.1, M5.1, M5.4 ; artefacts rechargeables/accessibles |
| L5 - README.txt | M1.2, M5.1, M5.4 ; commandes réelles et exécution propre |
| B1/B2 - public, carte, format, abstention, exclusions | M1.1, M2.2, M2.3, M2.6, M4.2 ; contrat, dialogues, refus et erreurs mesurés |
| B3 - FastF1, causalité, calcul, licences, reconstruction | M1.2, M2.1, M5.1, M5.4 ; provenance, contraintes et accès documentés |
| B4 - quatre partitions, 400 exemples, A, mini-test | M2.1–M2.5 ; manifestes, contrôle manuel et tableau exploratoire |
| B5 - règles et rôles croisés | M1.1 et toutes les fiches ; contrat et responsable/relecteur distincts |
| B6 - 85/15, B, mêmes réglages, analyse sans biais favorable | M2.2, M3.1, M3.2 ; correspondance 340/60, configs et analyse |
| B7 - gel, final ~200, 40 cas 0–2, aveugle, IC par course | M3.2, M4.1, M4.2 ; manifeste de gel, sorties uniques et notes |
| B8 - langues, carte/UI, rerun, vidéo, suivi | M2.6, M5.1–M5.4 et workflow commun ; preuves/livrables et mises à jour futures des supports |
| B9 - autre graine/V2 et OpenF1 facultatifs | Options de la roadmap ; aucun créneau réservé ni dépendance du rendu |

