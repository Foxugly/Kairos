# Kairos — conception

*2026-11-09. Dépôt public `Foxugly/Kairos` (« le moment opportun » — fait la paire avec Chronos), vhost `kairos.foxugly.com`.*

## Intention

Renaud veut un outil de trading **autonome** qui, toutes les 5 minutes, lit l'actualité économique
et les cours d'une centaine de valeurs, repère des signaux (figures techniques sur les courbes,
réactions typiques aux nouvelles), s'appuie sur l'IA pour trancher, et **prend puis relâche des
positions**. Dans un premier temps tout est **simulé** (aucun ordre réel) : le but est de mesurer
si l'approche gagne de l'argent avant d'envisager un vrai broker.

Il suit l'outil depuis un frontend : positions ouvertes et fermées, gains, pertes.

**Critère d'échec (Renaud) :** que les positions soient perdantes. Précisé ensemble : on juge le
résultat **global, net de frais, comparé à un indice acheté et gardé** — une stratégie gagnante perd
aussi sur une partie de ses lignes.

## Objectifs

1. **Collecte** : flux RSS d'actualité économique + cours des valeurs suivies, toutes les 5 minutes.
2. **Analyse** : figures techniques calculées en code ; réactions aux nouvelles évaluées par l'IA ;
   décision acheter / garder / vendre, **avec sa justification enregistrée**.
3. **Simulation** : un broker simulé exécute les ordres sur papier ; le portefeuille est revalorisé
   à chaque cycle.
4. **Frontend** : positions, gains et pertes, journal des décisions, comparaison à l'indice.

## Non-objectifs (pour cette première version)

- Aucun ordre réel. Aucun broker réel branché (mais l'architecture le permet, voir plus bas).
- Pas de vente à découvert, pas de levier, pas d'options.
- Pas de trading haute fréquence : le cycle est de 5 minutes, les cours gratuits sont retardés
  (~15 min) — acceptable pour une simulation.
- Pas d'application mobile, pas de notifications (à discuter plus tard).

## Anti-objectifs

- Un outil qui « marche » techniquement mais dont on ne peut pas savoir **pourquoi** il a pris une
  position : chaque décision doit être traçable (nouvelle, figure, réponse de l'IA, règle déclenchée).
- Une facture d'IA disproportionnée : l'IA n'est pas appelée 100 fois toutes les 5 minutes.
- Un résultat flatteur parce que la simulation est irréaliste (pas de frais, pas de change, ordres
  hors séance, prix connus avant qu'ils ne le soient).

## Décisions de Renaud

- **Modèle de la flotte** : Django (API JSON) + Angular 21 dans un même dépôt (`backend/`,
  `frontend/`), déployé sur la box comme FoxHouse (GitHub Actions → OIDC → SSM, SSM Parameter Store,
  Sentry, UptimeRobot, `/health/`). Référence : `D:\Projects\PycharmProjects\FoxHouse`.
- **Plusieurs sources d'information et plusieurs brokers** : modules interchangeables.
- **Univers** : ~100 valeurs. Noyau imposé : Apple, Microsoft, Alphabet, Amazon, Meta, Nvidia,
  TotalEnergies, Tesla (et les autres sociétés de Musk **si et quand** elles sont cotées). L'outil
  **propose** le complément, Renaud valide.
- **Analyse** : les deux familles de signaux — figures sur les courbes (tête-épaules, cassure de
  résistance, moyennes mobiles…) et réactions typiques aux nouvelles (résultats, rachats, enquêtes…).
- **Règles de simulation** (proposées par Claude, acceptées telles quelles) :
  - capital fictif **10 000 €** ;
  - **5 % max par position** (~500 €), **20 positions ouvertes max**, le reste en liquidités ;
  - achat seulement ;
  - sorties : **stop-loss −5 %**, **stop suiveur** (trailing) pour protéger les gains, sortie décidée
    par l'analyse (mauvaise nouvelle, figure baissière) ;
  - **frais simulés proches de Bolero**, **conversion USD/EUR**, ordres **seulement en séance** de la
    bourse de chaque valeur ;
  - **comparaison** permanente à 10 000 € placés au départ sur un indice et gardés ;
  - tous ces paramètres réglables (admin Django).
- Broker réel actuel de Renaud : **Bolero**, sans API publique connue — le choix d'un broker réel
  est reporté.

## Architecture

### Backend (Django), apps proposées

- `marche/` — **valeurs** (`Valeur` : ticker, nom, place de cotation, devise, active/proposée) et
  **cours** (bougies 5 min et journalières). Calendrier de séance par place.
- `sources/` — **interface `SourceCours`** et **interface `SourceNouvelles`**, avec un registre
  comme le registre des jeux de FoxHouse. Implémentations de départ : cours via `yfinance` ; nouvelles
  via une liste de **flux RSS configurables en admin** (URL, langue, actif). Les nouvelles sont
  dédoublonnées (URL / hash du titre) et rattachées aux valeurs qu'elles citent.
- `analyse/` — **signaux techniques en code pur** (sans Django, testables) : moyennes mobiles,
  RSI, cassures de supports/résistances, quelques figures classiques. **Appel à l'IA (Claude)**
  seulement quand une nouvelle concerne une valeur suivie ou qu'un signal technique se déclenche ;
  l'IA reçoit la nouvelle, les indicateurs et la position éventuelle, et rend une réponse
  **structurée** (décision, confiance, horizon, justification). Budget mensuel d'IA plafonné et
  réglable : au‑delà, l'outil continue sur les seules règles techniques et le signale.
- `courtage/` — **interface `Broker`** (passer un ordre, solde, positions) et registre.
  Implémentation : `BrokerSimule` (exécution au dernier cours connu, frais, change). Un
  **portefeuille** est rattaché à un broker ; plusieurs portefeuilles peuvent tourner en parallèle.
- **Frais des brokers** (demande explicite de Renaud) : chaque broker a son **barème de frais**,
  objet à part, réglable en admin et daté (un barème change ; une position garde celui de son
  exécution). Il couvre :
  - les **frais de courtage** par ordre, par place de cotation (fixe + %, minimum, maximum, paliers) ;
  - les **frais de change** (marge sur USD/EUR) pour les valeurs hors euro ;
  - la **taxe sur les opérations de bourse (TOB)** belge, à l'achat comme à la vente ;
  - d'éventuels frais de place ou de garde.

  Le barème de départ reproduit celui de **Bolero** en vigueur (à relever sur son site au moment de
  la construction, avec sa date). L'interface `Broker` expose « combien coûterait cet ordre » : la
  décision d'acheter en tient compte (pas d'achat dont le gain attendu ne couvre pas l'aller‑retour
  des frais). Chaque ordre enregistre le détail de ses frais ; **tous les gains et pertes affichés
  sont nets de frais**, et le tableau de bord montre le **total des frais payés**.
- `portefeuille/` — `Portefeuille`, `Position` (ouverte/fermée, prix d'entrée/sortie, frais,
  stop), `Ordre`, `Decision` (lien vers les signaux, nouvelles et réponse IA qui l'ont motivée),
  historique de valorisation (pour la courbe et la comparaison à l'indice).
- `accounts/`, `config/` — comme la flotte (`/health/`).

### Le cycle de 5 minutes

Un **timer systemd** (pas de Celery, pas de Redis — comme FoxHouse) lance une commande de gestion
`cycle` toutes les 5 minutes, avec un verrou pour qu'un cycle lent ne se superpose pas au suivant :

1. relever les nouvelles des sources ;
2. relever les cours des valeurs dont la place est en séance (et le taux USD/EUR) ;
3. calculer les signaux ; appeler l'IA là où c'est justifié ;
4. décider : sorties d'abord (stops, signaux de vente), puis entrées dans la limite des règles ;
5. faire exécuter les ordres par le broker du portefeuille ;
6. revaloriser le portefeuille et l'indice de comparaison ; enregistrer.

Chaque étape journalise ce qu'elle a fait ; une erreur d'une source n'arrête pas le cycle (Sentry).

### Proposition de l'univers

Une commande produit une **liste proposée** (les 8 imposées + grandes capitalisations liquides des
États‑Unis et d'Europe, p. ex. S&P 100 et Euro Stoxx 50), Renaud active/désactive dans l'admin.

### Frontend (Angular)

Accès réservé (connexion du compte de la flotte) — les écrans exposent la stratégie.

- **Tableau de bord** : valeur du portefeuille, gain/perte total net de frais (€ et %), total des frais payés, écart avec l'indice,
  courbe portefeuille vs indice, taux de positions gagnantes, liquidités.
- **Positions ouvertes** : valeur, prix d'entrée, cours actuel, gain/perte latent, stop.
- **Positions fermées** : gain/perte réalisé, durée, motif de sortie.
- **Journal des décisions** : chaque décision avec sa justification (nouvelle, signaux, réponse IA).
- **Valeurs** : univers suivi, dernier cours, derniers signaux et nouvelles.

Rafraîchissement automatique de l'affichage (rythme du cycle).

## Contraintes

- Fleet : conventions de `~/.claude/CLAUDE.md` et `OPERATIONS.md` (permissions, SSM, unités
  durcies, CI Postgres via ECR en cache, actions épinglées par SHA, Dependabot, branche protégée).
  Port **8014** (prochain libre), pas de Redis.
- Dépôt **public** comme la flotte : aucun secret ni réglage sensible dans le dépôt.
- La clé API Anthropic vit dans SSM (`/kairos/prod/`), jamais dans le dépôt.
- Code, commentaires et messages en français (comme FoxHouse).
- Les sources gratuites ont des conditions d'utilisation et des limites de débit : les respecter
  (cadence, cache), et pouvoir changer de source sans toucher au reste.

## Évaluation (proposée par Claude, acceptée)

- **Backtest technique** : avant le direct, rejouer les seules règles techniques sur plusieurs années
  de cours **journaliers** (gratuits) de l'univers, avec les mêmes frais et le même indice. But :
  écarter des règles perdantes d'emblée. Pas de backtest des nouvelles ni de l'IA (pas d'historique
  de nouvelles daté fiable et gratuit).
- **Direct** : point mensuel ; **verdict à 3 mois** — réussi si le portefeuille « IA » bat l'indice
  net de frais **et** bat le portefeuille « Technique ». Indication, pas preuve : 3 mois sont courts.

## IA : budget et compte

- L'abonnement Claude Max de Renaud **ne couvre pas l'API**. Kairos utilise une **clé API**
  (console.anthropic.com), facturée à l'usage, rangée dans SSM.
- **Plafond : 30 à 50 € par mois** — réglé dans Kairos (par portefeuille, voir plus bas) **et** comme
  limite de dépense sur la console. Kairos suit sa dépense (jetons consommés × tarif) et l'affiche.

## Choix de Claude (après relecture)

- **Indice de comparaison** : un ETF MSCI World coté en euros (iShares Core MSCI World, `IWDA.AS`),
  acheté une fois au départ avec les mêmes frais simulés, puis gardé. Pas de change à gérer.
- **Règles par portefeuille** : capital, tailles, stops, frais, usage de l'IA et budget d'IA
  appartiennent au **portefeuille**, pas à un réglage global ; chaque décision est rattachée à son
  portefeuille.
- **Portefeuille témoin** : deux portefeuilles tournent dès le départ sur le même univers —
  « IA » (signaux + IA) et « Technique » (signaux seuls, sans IA). On voit ainsi ce que l'IA apporte,
  et l'épuisement du budget d'IA ne fausse pas la comparaison.

## Laissé au constructeur

- Choix précis des indicateurs et figures de la première version, et des flux RSS de départ.
- Modèle(s) Claude exact(s) et format de la réponse structurée (dernier modèle disponible).
- Modèle de frais « proche de Bolero » (barème simplifié), source du taux de change.
- Découpage en étapes livrables (suggestion : collecte → simulation sur règles techniques seules →
  IA → frontend complet).
