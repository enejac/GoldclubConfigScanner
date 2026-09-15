# Changelog

What landed on `master`. One line per merged pull request, newest first.
Updated automatically when a PR is merged.

## 2026-09-15

- Load cabinet when Enter is pressed after changing the IP ([#80](https://github.com/enejac/GoldclubConfigScanner/pull/80))
- Live Push: make Games/math Reset restore the live RTP and bets ([#79](https://github.com/enejac/GoldclubConfigScanner/pull/79))
- Live Push: show Magic wheel only when the gamepack has it ([#78](https://github.com/enejac/GoldclubConfigScanner/pull/78))
- Live Push: edit bet steps and RTP per game ([#77](https://github.com/enejac/GoldclubConfigScanner/pull/77))
- Live Push: Check SlotLog uses the loaded Goldclub root, not typed c$ ([#76](https://github.com/enejac/GoldclubConfigScanner/pull/76))
- Cabinet dropdown: serial labels + auto-resolve bare IPs ([#75](https://github.com/enejac/GoldclubConfigScanner/pull/75))
- Snapshots: keep licence XML in Licenses and the WIBU stub in slot only ([#74](https://github.com/enejac/GoldclubConfigScanner/pull/74))

## 2026-09-14

- Say the dead WinRM channel once, not four times ([#73](https://github.com/enejac/GoldclubConfigScanner/pull/73))
- Exit Config Scanner on window close so it does not stay in Task Manager ([#72](https://github.com/enejac/GoldclubConfigScanner/pull/72))
- Live Push: reload OneHand for cashout and keep Apply status on the panel ([#71](https://github.com/enejac/GoldclubConfigScanner/pull/71))
- Live Push: add Cashless to the Cashout button list ([#70](https://github.com/enejac/GoldclubConfigScanner/pull/70))
- Snapshots: show Create a backup next to Auto-start stack ([#69](https://github.com/enejac/GoldclubConfigScanner/pull/69))
- Keep pytest tmp paths out of the remembered cabinet ([#68](https://github.com/enejac/GoldclubConfigScanner/pull/68))
- Live Push: give door labels and checkbox text a bit of margin ([#67](https://github.com/enejac/GoldclubConfigScanner/pull/67))
- Live Push: warn when Apply needs a stack restart or RAM clear ([#66](https://github.com/enejac/GoldclubConfigScanner/pull/66))
- Live Push: read Language from jurisdiction_config + slot\languages (2.0.1/3.0.0 images) ([#65](https://github.com/enejac/GoldclubConfigScanner/pull/65))
- Rebuild ConfigScanner.exe from master a9ef44f (2026-09-14 07:57) ([#64](https://github.com/enejac/GoldclubConfigScanner/pull/64))
- Snapshots: autoload the last Live Push cabinet so Create is ready, and drop flag combo chrome ([#63](https://github.com/enejac/GoldclubConfigScanner/pull/63))
- Restore: make the live backup an off-by-default checkbox ([#62](https://github.com/enejac/GoldclubConfigScanner/pull/62))
- Snapshots: Create without GUI freeze; drop placeholder banner and status-bar stamp ([#61](https://github.com/enejac/GoldclubConfigScanner/pull/61))
- Live Push: show real country-flag bitmaps because flag_spanish is oft… ([#60](https://github.com/enejac/GoldclubConfigScanner/pull/60))
- Cursor/smb write without winrm ([#59](https://github.com/enejac/GoldclubConfigScanner/pull/59))
- Restore and Live Push: SMB write when WinRM is not listening ([#58](https://github.com/enejac/GoldclubConfigScanner/pull/58))
- Live Push: read Language from jurisdiction_config + slot\languages (2.0.1/3.0.0 images) ([#57](https://github.com/enejac/GoldclubConfigScanner/pull/57))
- Rebuild ConfigScanner.exe from master a9ef44f (2026-09-14 07:57) ([#56](https://github.com/enejac/GoldclubConfigScanner/pull/56))
- Rebuild ConfigScanner.exe from master 8abecfd (2026-09-11 15:16) ([#55](https://github.com/enejac/GoldclubConfigScanner/pull/55))

## 2026-09-11

- Screenshot button works while an 'Apply finished with errors' popup is open ([#54](https://github.com/enejac/GoldclubConfigScanner/pull/54))
- Snapshots: same Cabinet row as Live Push, one shared remembered cabinet ([#53](https://github.com/enejac/GoldclubConfigScanner/pull/53))
- Live Push: cut cabinet load time (shared exe buffer, read cache, parallel stages) ([#52](https://github.com/enejac/GoldclubConfigScanner/pull/52))
- Live Push: write settings even when the game cannot be stopped from t… ([#51](https://github.com/enejac/GoldclubConfigScanner/pull/51))
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
