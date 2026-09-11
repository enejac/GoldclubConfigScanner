# Changelog

What landed on `master`. One line per merged pull request, newest first.
Updated automatically when a PR is merged.

## 2026-09-11

- Rebuild ConfigScanner.exe from master 390c64c (2026-09-11 13:07) ([#50](https://github.com/enejac/GoldclubConfigScanner/pull/50))
- Restore native move and resize on the Config Scanner window ([#49](https://github.com/enejac/GoldclubConfigScanner/pull/49))
- Live Push: never paint red for values the running cabinet already proves ([#48](https://github.com/enejac/GoldclubConfigScanner/pull/48))
- Auto-update a short changelog on every merged PR ([#22](https://github.com/enejac/GoldclubConfigScanner/pull/22))
- Rebuild ConfigScanner.exe and portable zip (2026-09-10 11:48) ([#20](https://github.com/enejac/GoldclubConfigScanner/pull/20))
- Fix OneHand Debug SKU showing as Release in Live Push ([#18](https://github.com/enejac/GoldclubConfigScanner/pull/18))
- Align bet steps with market packs; include RouletteGame in slot snapshots ([#15](https://github.com/enejac/GoldclubConfigScanner/pull/15))

## 2026-09-10

- Write magic-wheel knobs to jurisdiction_config; fix Live Push right-click ([#17](https://github.com/enejac/GoldclubConfigScanner/pull/17))
- Start Release OneHand via slot game-start after Live Push ([#16](https://github.com/enejac/GoldclubConfigScanner/pull/16))
- Fix Live Push SAS apply causing AurumEGM NRE ([#14](https://github.com/enejac/GoldclubConfigScanner/pull/14))
- Ship Windows exe as ConfigScanner.exe only ([#13](https://github.com/enejac/GoldclubConfigScanner/pull/13))
- Fix Slot full-snapshot restore blocked by leftover Ruleta ([#12](https://github.com/enejac/GoldclubConfigScanner/pull/12))
- Keep ConfigScanner alive on Apply restart without USB scripts ([#10](https://github.com/enejac/GoldclubConfigScanner/pull/10))
- Fix OneHand Debug detection in Live Push header ([#9](https://github.com/enejac/GoldclubConfigScanner/pull/9))
- Allow Live Push on any 10.0.0.x cabinet ([#8](https://github.com/enejac/GoldclubConfigScanner/pull/8))
- Remember window size and open Live Push maximized ([#7](https://github.com/enejac/GoldclubConfigScanner/pull/7))

## 2026-09-09

- Auto SMB login for lab cabinets (fix 1326 on .111) ([#2](https://github.com/enejac/GoldclubConfigScanner/pull/2))
- ConfigScanner.exe 2026-09-09 Windows build ([#1](https://github.com/enejac/GoldclubConfigScanner/pull/1))

## Earlier

Direct commits before GitHub PRs (9 Sep 2026 and earlier):

- OneHand version and Debug/Release in the Live Push header
- Licence push off by default on Debug OneHand
- Silent SMB `test`/`test` for `10.0.0.x` cabinets
- Live Push Load spinner and Restore backup
- Fork Config Scanner from Log Investigator
