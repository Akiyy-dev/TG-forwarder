# Changelog

## [0.3.3](https://github.com/Akiyy-dev/TG-forwarder/compare/v0.3.2...v0.3.3) (2026-07-17)


### Bug Fixes

* harden distributed forwarding lifecycle ([843efe5](https://github.com/Akiyy-dev/TG-forwarder/commit/843efe542282b0a5ef275edfc3ce13736086e2b1))

## [0.3.2](https://github.com/Akiyy-dev/TG-forwarder/compare/v0.3.1...v0.3.2) (2026-07-16)


### Bug Fixes

* distinguish SafeW sources in web ([f9ed1de](https://github.com/Akiyy-dev/TG-forwarder/commit/f9ed1deea81c80ee729187881a52d1292cdb96ec))

## [0.3.1](https://github.com/Akiyy-dev/TG-forwarder/compare/v0.3.0...v0.3.1) (2026-07-16)


### Bug Fixes

* install xz for safew image ([50c5927](https://github.com/Akiyy-dev/TG-forwarder/commit/50c5927ea1174430d30027986b850308cf0e0992))

## [0.3.0](https://github.com/Akiyy-dev/TG-forwarder/compare/v0.2.0...v0.3.0) (2026-07-16)


### Features

* add SafeW receiver compose architecture ([9cc7928](https://github.com/Akiyy-dev/TG-forwarder/commit/9cc79287785371b7a796e9bd2886a1a781a71a20))
* add SafeW receiver compose architecture ([f0466da](https://github.com/Akiyy-dev/TG-forwarder/commit/f0466dab591764e19e6edda854167417ab272ad7))
* publish release container images ([4714269](https://github.com/Akiyy-dev/TG-forwarder/commit/47142693ae568cdaf991bd527f9a0717d258be9e))


### Bug Fixes

* format settings and simplify readme ([5bb2c99](https://github.com/Akiyy-dev/TG-forwarder/commit/5bb2c99b9acbfd7978d820cdfc369deb83aede0d))

## [0.2.0](https://github.com/Akiyy-dev/TG-forwarder/compare/v0.1.0...v0.2.0) (2026-07-16)


### Features

* add telegram channel forwarder ([b569c21](https://github.com/Akiyy-dev/TG-forwarder/commit/b569c21de06364ff4258ee82efbde7a7b83161ff))
* auto-approve and publish reviews after configurable timeout ([bddcd98](https://github.com/Akiyy-dev/TG-forwarder/commit/bddcd98d20bc5eb4b6aa0b59c397e23a724692e9))
* channel multi-target binding, settings center, history, and admin UI polish ([a7812ef](https://github.com/Akiyy-dev/TG-forwarder/commit/a7812efdfb6572575bbfbc2e5a9454429c793c9e))
* **channels:** add publish modes and channel APIs (PRD28) ([da6c70d](https://github.com/Akiyy-dev/TG-forwarder/commit/da6c70d4a241cd12a03cb52496461b57374cd7e5))
* Chinese admin UI, has_media rules, and YAML config seeds ([0858d06](https://github.com/Akiyy-dev/TG-forwarder/commit/0858d0661bd5daad4fcb52d22c17816971ff2d05))
* Phase 2 web admin panel and review workflow ([917eae1](https://github.com/Akiyy-dev/TG-forwarder/commit/917eae163309031070a49e67c97e7b83cf465dde))
* Phase 2 web admin panel and review workflow ([f8a5f06](https://github.com/Akiyy-dev/TG-forwarder/commit/f8a5f06631db345220754210879bcfd6120c6082))
* **review:** add review list/detail/publish APIs (PRD24) ([d3cf55e](https://github.com/Akiyy-dev/TG-forwarder/commit/d3cf55ee0598c5919d26df4fa405dc57ab7c9127))
* **review:** add review state machine and REVIEW routing (PRD23) ([eba09b3](https://github.com/Akiyy-dev/TG-forwarder/commit/eba09b3208cab677955fb58b5bb885a2410ae335))
* **rules:** add DB-backed keyword rule engine (PRD26) ([ef5997e](https://github.com/Akiyy-dev/TG-forwarder/commit/ef5997eef05fccd2ea627ed22909fbfc1f6aedfd))
* **rules:** add rules CRUD, test, and reapply APIs (PRD27) ([19be1a6](https://github.com/Akiyy-dev/TG-forwarder/commit/19be1a6b08f7f6addb86338c8690872e0e3e37e7))
* **web:** add admin shell, login, and dashboard (PRD29) ([c349388](https://github.com/Akiyy-dev/TG-forwarder/commit/c3493881a8a6e00e4a7b58cd2a187ddccdb6648c))
* **web:** add API pagination and RBAC user admin (PRD22) ([22995cc](https://github.com/Akiyy-dev/TG-forwarder/commit/22995cca0ada64ba1ac3f8854af9fd4d0cafac28))
* **web:** add auth, AppContext, and SQLite WAL (PRD21) ([8f3f102](https://github.com/Akiyy-dev/TG-forwarder/commit/8f3f102016222b80ce0fe41b5394dcecbc22e321))
* **web:** add authenticated media streaming and preview (PRD25) ([157840e](https://github.com/Akiyy-dev/TG-forwarder/commit/157840e8014398544e889c31658a5e24e2b3f4c8))
* **web:** add review queue and detail pages (PRD30) ([96cb024](https://github.com/Akiyy-dev/TG-forwarder/commit/96cb024243dacfac50e593c34f25eb01cc46ea16))
* **web:** add rules and channels admin pages (PRD31) ([a52c4f7](https://github.com/Akiyy-dev/TG-forwarder/commit/a52c4f792b33f5ab4718928d24302716511617cc))
* **web:** add SSE status, system controls, and logs (PRD32) ([997f4c3](https://github.com/Akiyy-dev/TG-forwarder/commit/997f4c39e6a491cefccf7b9d6f7700d55dbdfaa7))


### Bug Fixes

* **ci:** satisfy mypy on MediaService._path_ok ([bda4bf3](https://github.com/Akiyy-dev/TG-forwarder/commit/bda4bf3d2e4eafb313c8a82d0f85425ad9c4f0f6))
* **ci:** satisfy ruff format and sync web lockfile ([36d2466](https://github.com/Akiyy-dev/TG-forwarder/commit/36d24669082906de4e3501c2ab0ce6c733745b40))
* keep unknown-access channels enabled and stop SPA swallowing /api paths ([5e913e3](https://github.com/Akiyy-dev/TG-forwarder/commit/5e913e3bb8dad3d74d8b4679ae1cea8322d7a993))
* **listener:** collect full media albums via Telethon Album events ([7e09138](https://github.com/Akiyy-dev/TG-forwarder/commit/7e0913882227d7b868f4d98257a2b3a0850ef444))
* resolve ruff SIM105 and E501 lint failures ([1207dd0](https://github.com/Akiyy-dev/TG-forwarder/commit/1207dd07524c372746316f461b91f6fd010019ba))
* **review:** rematerialize missing media on publish and preview ([d11664c](https://github.com/Akiyy-dev/TG-forwarder/commit/d11664cbd5966037dec6e96028f77ade0f0ef27b))
* **web:** pin emnapi packages for Linux npm ci ([516db42](https://github.com/Akiyy-dev/TG-forwarder/commit/516db42b0d70f162df95624f191e54d311d0f5d2))
* **web:** remove useBlocker crash on review detail ([265a234](https://github.com/Akiyy-dev/TG-forwarder/commit/265a234b08e955a51bb9ebc4449e62af5e6e1277))
* **web:** SPA refresh fallback and reviews Select blank page ([3db8949](https://github.com/Akiyy-dev/TG-forwarder/commit/3db8949985563a1f4ed57e5018c0ac4abc259ac9))


### Documentation

* **ci:** cover web build and document admin panel (PRD33) ([50274e9](https://github.com/Akiyy-dev/TG-forwarder/commit/50274e91f8273418e465b7c70c5f387f019784ea))
* document web admin panel setup and verification ([322ed3b](https://github.com/Akiyy-dev/TG-forwarder/commit/322ed3b346a32fa4cad030fb31a356a749392658))
