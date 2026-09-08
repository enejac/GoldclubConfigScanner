Config Scanner sidecar tools (keep this folder next to ConfigScanner.exe).
Do not run these on live math files in place — the scanner copies into a temp
folder first. Country Selector export still stages a nested CRYPT_TOOLS copy.

Encryptor.exe
  GoldClub JSON / ProgressiveSetup.xml cryptor (Link2Win and other theme math).
  Config Scanner calls this for read-only decrypt. Same job as a drop named
  Decryptor.exe.

BiOS Encryptor.exe
  Encrypt / decrypt BiOS 1.0.6 cabinet updates (.ws). GUI tool. JinLong CS
  packs on the share use this format.

BiOSCrypt.exe
  Encrypt / decrypt later Slot BiOS updates (.exe packages), not .ws.

JPCrypt.exe
  Encrypt / decrypt external Jackpot Controller updates (.exe). Different
  key than the Slot BiOS tools. JinLong JP controller zips use this family.

BiOS2_PackageGenerator.exe
  Official BiOS2 packer. Config Scanner uses it to decrypt / encrypt GameStar
  Country Selector .b2u (updateDecrypt / updateEncrypt). Must stay beside its
  two DLLs and .config; a lone copy of the exe crashes (missing log4net).

BiOS2_PackageGenerator.exe.config
  .NET settings for BiOS2_PackageGenerator.exe. Required next to that exe.

log4net.dll
  Logging library required by BiOS2_PackageGenerator.exe. Not used by the
  scanner itself.

ICSharpCode.SharpZipLib.dll
  Zip library required by BiOS2_PackageGenerator.exe to open / write packs.
