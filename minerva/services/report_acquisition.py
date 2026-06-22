"""
Report Acquisition Service — single source of truth for the report-to-queue workflow.

Owns: scope inference, entry classification, queue construction, duplicate
exclusion, destination generation, status updates.  Qt-agnostic — operates
on domain types and talks to ``MinervaDB`` / ``MinervaState``.
"""

from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from minerva.domain.reports import (
    AcquisitionPlan,
    AcquisitionSummary,
    MatchPolicy,
    PlannedFile,
    QueueResult,
    ReportOutcome,
    ReportScope,
    ReportSummary,
    ResolutionState,
    ReviewEntry,
    ScopeInferenceRequired,
)
from minerva_db import (
    DatEntry,
    MinervaDB,
    StemSizeMatch,
    parse_dat_file,
    parse_rv_fix_csv,
    stem_from_romname,
)
from minerva_state import MinervaState

log = logging.getLogger(__name__)

# Maps DAT system names → RomM folder slugs for RomM-compatible destinations.
# 678 entries — covers all gaming platforms in the torrent index.
# Built from the canonical RomM platform list (https://romm.app).
# Variant suffixes (Aftermarket, Private, BigEndian, Decrypted, etc.)
# and prefixes (Non-Redump, RA, Source Code, Unofficial) map to the same
# slug as their parent platform.
_SYSTEM_TO_ROMM_SLUG: dict[str, str] = {
    "3DO": "3do",
    "ACT - Apricot PC Xi": "apricot-pc-xi",
    "APF - Imagination Machine": "apf-imagination-machine",
    "APF - MP-1000": "apf-mp-1000",
    "Acorn - Archimedes": "acorn-archimedes",
    "Acorn - Atom (Tapes) (Bitstream)": "acorn-atom",
    "Acorn - Risc PC (Flux)": "acorn-risc-pc",
    "Acorn RISC OS - Flash Media (Misc)": "acorn-risc-os",
    "Amstrad - CPC (Flux)": "amstrad-cpc",
    "Amstrad - CPC (Misc)": "amstrad-cpc",
    "Analogue - Analogue Pocket": "analogue-pocket",
    "Apple - I (Tapes)": "apple-1",
    "Apple - II (A2R)": "apple-2",
    "Apple - II (WOZ)": "apple-2",
    "Apple - II (Waveform)": "apple-2",
    "Apple - II Plus (Flux)": "apple-2",
    "Apple - II Plus (WOZ)": "apple-2",
    "Apple - IIGS (A2R)": "apple-iigs",
    "Apple - IIGS (WOZ)": "apple-iigs",
    "Apple - IIe (A2R)": "apple-2",
    "Apple - IIe (Kryoflux)": "apple-2",
    "Apple - IIe (WOZ)": "apple-2",
    "Apple - Macintosh": "macintosh",
    "Apple - Macintosh (A2R)": "macintosh",
    "Apple - Macintosh (BETA) (Bitstreams)": "macintosh",
    "Apple - Macintosh (BETA) (FluxDumps)": "macintosh",
    "Apple - Macintosh (DC42)": "macintosh",
    "Apple - Macintosh (KryoFlux)": "macintosh",
    "Apple - Macintosh (Uncategorized)": "macintosh",
    "Apple - Macintosh (WOZ)": "macintosh",
    "Apple - Macintosh - SBI Subchannels": "macintosh",
    "Apple-Bandai - Pippin (Floppies)": "pippin",
    "Arcade": "arcade",
    "Arcade - Hasbro - VideoNow": "videonow",
    "Arcade - Hasbro - VideoNow Color": "videonow",
    "Arcade - Hasbro - VideoNow Jr": "videonow",
    "Arcade - Hasbro - VideoNow XP": "videonow",
    "Arcade - Konami - FireBeat": "konami-firebeat",
    "Arcade - Konami - M2": "konami-m2",
    "Arcade - Konami - System 573": "konami-system-573",
    "Arcade - Konami - System GV": "konami-system-gv",
    "Arcade - Konami - e-Amusement": "konami-e-amusement",
    "Arcade - Namco - Sega - Nintendo - Triforce": "triforce",
    "Arcade - Namco - Sega - Nintendo - Triforce - GDI Files": "triforce",
    "Arcade - Namco - System 246": "namco-system-246",
    "Arcade - PC-based": "arcade",
    "Arcade - Sega - Chihiro": "sega-chihiro",
    "Arcade - Sega - Chihiro - GDI Files": "sega-chihiro",
    "Arcade - Sega - Lindbergh": "sega-lindbergh",
    "Arcade - Sega - Naomi": "naomi",
    "Arcade - Sega - Naomi - GDI Files": "naomi",
    "Arcade - Sega - Naomi 2": "naomi-2",
    "Arcade - Sega - Naomi 2 - GDI Files": "naomi-2",
    "Arcade - Sega - RingEdge": "sega-ringedge",
    "Arcade - Sega - RingEdge 2": "sega-ringedge-2",
    "Arduboy": "arduboy",
    "Arduboy Inc - Arduboy": "arduboy",
    "Atari - 8-bit Family": "atari-800",
    "Atari - 8-bit Family (Aftermarket)": "atari-800",
    "Atari - 8-bit Family (Kryoflux)": "atari-800",
    "Atari - Atari 2600": "atari-2600",
    "Atari - Atari 2600 (Aftermarket)": "atari-2600",
    "Atari - Atari 2600 (BIN)": "atari-2600",
    "Atari - Atari 2600 (Private)": "atari-2600",
    "Atari - Atari 5200": "atari-5200",
    "Atari - Atari 7800 (A78) (Aftermarket)": "atari-7800",
    "Atari - Atari 7800 (A78) (Private)": "atari-7800",
    "Atari - Atari 7800 (BIN)": "atari-7800",
    "Atari - Atari 7800 (BIN) (Aftermarket)": "atari-7800",
    "Atari - Atari 7800 (BIN) (Private)": "atari-7800",
    "Atari - Atari Jaguar (ABS) (Aftermarket)": "jaguar",
    "Atari - Atari Jaguar (COF) (Aftermarket)": "jaguar",
    "Atari - Atari Jaguar (J64)": "jaguar",
    "Atari - Atari Jaguar (J64) (Aftermarket)": "jaguar",
    "Atari - Atari Jaguar (JAG)": "jaguar",
    "Atari - Atari Jaguar (JAG) (Aftermarket)": "jaguar",
    "Atari - Atari Jaguar (ROM)": "jaguar",
    "Atari - Atari Jaguar (ROM) (Aftermarket)": "jaguar",
    "Atari - Atari Lynx (BLL)": "lynx",
    "Atari - Atari Lynx (BLL) (Aftermarket)": "lynx",
    "Atari - Atari Lynx (LNX)": "lynx",
    "Atari - Atari Lynx (LNX) (Aftermarket)": "lynx",
    "Atari - Atari Lynx (LNX) (Private)": "lynx",
    "Atari - Atari Lynx (LYX)": "lynx",
    "Atari - Atari Lynx (LYX) (Aftermarket)": "lynx",
    "Atari - Atari Lynx (LYX) (Private)": "lynx",
    "Atari - Atari ST": "atari-st",
    "Atari - Atari ST (Flux)": "atari-st",
    "Atari - Jaguar CD Interactive Multimedia System": "jaguar",
    "Bally - Astrocade": "astrocade",
    "Bally - Astrocade (Tapes)": "astrocade",
    "Bally - Astrocade (Tapes) (WAV)": "astrocade",
    "Bandai - Design Master Denshi Mangajuku": "bandai-design-master",
    "Bandai - Gundam RX-78": "gundam-rx-78",
    "Bandai - Pippin": "pippin",
    "Bandai - Playdia Quick Interactive System": "playdia",
    "Bandai - WonderSwan": "wonderswan",
    "Bandai - WonderSwan Color": "wonderswan-color",
    "Bandai - WonderSwan Color (Aftermarket)": "wonderswan-color",
    "Bandai - WonderSwan Color [T-En] Collection": "wonderswan-color",
    "Bandai - WonderSwan [T-En] Collection": "wonderswan",
    "Bandai Little Jammer (BIN)": "bandai-little-jammer",
    "Bandai Little Jammer Pro (BIN)": "bandai-little-jammer",
    "Benesse - Pocket Challenge V2": "pocket-challenge-v2",
    "Benesse - Pocket Challenge W": "pocket-challenge-w",
    "Bit Corporation - Gamate": "gamate",
    "Blaze Entertainment - Evercade": "evercade",
    "Capcom": "cps1",
    "Casio - Loopy (BigEndian)": "casio-loopy",
    "Casio - Loopy (LittleEndian)": "casio-loopy",
    "Casio - Loopy [T-En] Collection": "casio-loopy",
    "Casio - PV-1000": "casio-pv-1000",
    "Coleco - ColecoVision": "colecovision",
    "Commodore - Amiga": "amiga",
    "Commodore - Amiga (Bitstream)": "amiga",
    "Commodore - Amiga (Flux)": "amiga",
    "Commodore - Amiga CD": "amiga",
    "Commodore - Amiga CD32": "amiga-cd32",
    "Commodore - Amiga CDTV": "amiga",
    "Commodore - BX256-80HP": "c128",
    "Commodore - C128": "c128",
    "Commodore - C16, C116 & Plus-4": "plus-4",
    "Commodore - C64DTV": "c64",
    "Commodore - C65": "c65",
    "Commodore - Commodore 64": "c64",
    "Commodore - Commodore 64 (Aftermarket)": "c64",
    "Commodore - Commodore 64 (Headerless)": "c64",
    "Commodore - Commodore 64 (PP)": "c64",
    "Commodore - Commodore 64 (Tapes)": "c64",
    "Commodore - MAX Machine & VIC10": "vic-10",
    "Commodore - PET": "pet",
    "Commodore - Plus-4": "plus-4",
    "Commodore - VIC-20": "vic-20",
    "Commodore - VIC20": "vic-20",
    "Elektronika": "elektronika",
    "Elektronska Industrija Nis": "elektronska-industrija-nis",
    "Emerson - Arcadia 2001": "arcadia-2001",
    "Entex - Adventure Vision": "adventure-vision",
    "Epoch - Game Pocket Computer": "epoch-game-pocket-computer",
    "Epoch - Super Cassette Vision": "super-cassette-vision",
    "Fairchild - Channel F": "fairchild-channel-f",
    "Front Fareast": "front-fareast",
    "Fujitsu - FM Towns (Flux)": "fm-towns",
    "Fujitsu - FM Towns (HDM)": "fm-towns",
    "Fujitsu - FM-7 (Bitstream)": "fm-7",
    "Fujitsu - FM-7 (Flux)": "fm-7",
    "Fujitsu - FM-7 (Sector)": "fm-7",
    "Fujitsu - FM-7 (Tapes) (Bitstream)": "fm-7",
    "Fujitsu - FM-7 (Tapes) (Waveform)": "fm-7",
    "Fujitsu - FM-Towns": "fm-towns",
    "Fujitsu - FM-Towns [T-En] Collection": "fm-towns",
    "Fujitsu - FMR50 (Flux)": "fmr50",
    "Fukutake Publishing - StudyBox": "studybox",
    "Funtech - Super Acan": "super-acan",
    "GCE - Vectrex": "vectrex",
    "Gakken": "gakken",
    "Galaksija": "galaksija",
    "GamePark - GP2X": "gp2x",
    "GamePark - GP32": "gp32",
    "Google - Android (Amazon Appstore) (APK)": "android",
    "Google - Android (Google Play Store) (APK)": "android",
    "Google - Android (Misc) (APK)": "android",
    "Google - Android (Samsung Galaxy Apps) (APK)": "android",
    "Hartung - Game Master": "game-master",
    "Hitachi - S1 (Waveform)": "hitachi-s1",
    "HomeLab": "homelab",
    "IBM - PC and Compatibles (Digital) (Amazon)": "pc",
    "IBM - PC and Compatibles (Digital) (BOOTH)": "pc",
    "IBM - PC and Compatibles (Digital) (Ci-en)": "pc",
    "IBM - PC and Compatibles (Digital) (DLsite)": "pc",
    "IBM - PC and Compatibles (Digital) (DLsite) (Hentai)": "pc",
    "IBM - PC and Compatibles (Digital) (Denpasoft)": "pc",
    "IBM - PC and Compatibles (Digital) (Desura)": "pc",
    "IBM - PC and Compatibles (Digital) (Epic Games Launcher)": "pc",
    "IBM - PC and Compatibles (Digital) (FANZA)": "pc",
    "IBM - PC and Compatibles (Digital) (FANZA) (Doujin)": "pc",
    "IBM - PC and Compatibles (Digital) (Flash)": "pc",
    "IBM - PC and Compatibles (Digital) (Freem!)": "pc",
    "IBM - PC and Compatibles (Digital) (GOG)": "pc",
    "IBM - PC and Compatibles (Digital) (GamersGate)": "pc",
    "IBM - PC and Compatibles (Digital) (Games for Windows Live)": "pc",
    "IBM - PC and Compatibles (Digital) (Games for Windows Live) (Deprecated)": "pc",
    "IBM - PC and Compatibles (Digital) (Getchu.com)": "pc",
    "IBM - PC and Compatibles (Digital) (Groupees)": "pc",
    "IBM - PC and Compatibles (Digital) (Humble Bundle)": "pc",
    "IBM - PC and Compatibles (Digital) (JAST USA)": "pc",
    "IBM - PC and Compatibles (Digital) (Johren)": "pc",
    "IBM - PC and Compatibles (Digital) (Kagura Games)": "pc",
    "IBM - PC and Compatibles (Digital) (MangaGamer)": "pc",
    "IBM - PC and Compatibles (Digital) (Microsoft Store)": "pc",
    "IBM - PC and Compatibles (Digital) (Misc)": "pc",
    "IBM - PC and Compatibles (Digital) (Misc) (Hentai)": "pc",
    "IBM - PC and Compatibles (Digital) (NovelGameCollection)": "pc",
    "IBM - PC and Compatibles (Digital) (Press Kits)": "pc",
    "IBM - PC and Compatibles (Digital) (Steam)": "pc",
    "IBM - PC and Compatibles (Digital) (Steam) (Hentai)": "pc",
    "IBM - PC and Compatibles (Digital) (Unknown)": "pc",
    "IBM - PC and Compatibles (Digital) (Updates and DLC)": "pc",
    "IBM - PC and Compatibles (Flash Media)": "pc",
    "IBM - PC and Compatibles (Flux)": "pc",
    "IBM - PC and Compatibles (IPF)": "pc",
    "IBM - PC and Compatibles (LooseFilesArchive)": "pc",
    "IBM - PC and Compatibles (SCP)": "pc",
    "IBM - PC and Compatibles (Tiger Electronics - Net Jet)": "pc",
    "IBM - PC compatible - 0-9": "pc",
    "IBM - PC compatible - A": "pc",
    "IBM - PC compatible - B": "pc",
    "IBM - PC compatible - C": "pc",
    "IBM - PC compatible - D": "pc",
    "IBM - PC compatible - E": "pc",
    "IBM - PC compatible - F": "pc",
    "IBM - PC compatible - G": "pc",
    "IBM - PC compatible - H": "pc",
    "IBM - PC compatible - I": "pc",
    "IBM - PC compatible - J": "pc",
    "IBM - PC compatible - K": "pc",
    "IBM - PC compatible - L": "pc",
    "IBM - PC compatible - M": "pc",
    "IBM - PC compatible - N": "pc",
    "IBM - PC compatible - O": "pc",
    "IBM - PC compatible - P": "pc",
    "IBM - PC compatible - Q": "pc",
    "IBM - PC compatible - R": "pc",
    "IBM - PC compatible - S": "pc",
    "IBM - PC compatible - SBI Subchannels": "pc",
    "IBM - PC compatible - T": "pc",
    "IBM - PC compatible - U": "pc",
    "IBM - PC compatible - V": "pc",
    "IBM - PC compatible - W": "pc",
    "IBM - PC compatible - X": "pc",
    "IBM - PC compatible - Y": "pc",
    "IBM - PC compatible - Z": "pc",
    "IBM - PC compatible - _": "pc",
    "Incredible Technologies - Eagle": "incredible-technologies-eagle",
    "Interton - VC 4000": "interton-vc-4000",
    "Konami - Picno": "konami-picno",
    "LeapFrog - Explorer": "leapfrog-explorer",
    "LeapFrog - LeapPad": "leapfrog-leappad",
    "LeapFrog - Leapster Learning Game System": "leapster",
    "Leonardo Miliani": "leonardo-miliani",
    "Luxor - ABC 800 (Flux)": "luxor-abc-800",
    "MGT": "mgt",
    "MSX": "msx",
    "Magnavox - Odyssey 2": "magnavox-odyssey-2",
    "Matra Hachette": "matra-hachette",
    "Mattel - Fisher-Price iXL": "fisher-price-ixl",
    "Mattel - HyperScan": "hyperscan",
    "Mattel - Intellivision": "intellivision",
    "Mattel - Intellivision (Aftermarket)": "intellivision",
    "Microsoft - MSX": "msx",
    "Microsoft - MSX (Aftermarket)": "msx",
    "Microsoft - MSX Turbo-R [T-En] Collection": "msx-turbo-r",
    "Microsoft - MSX [T-En] Collection": "msx",
    "Microsoft - MSX2": "msx2",
    "Microsoft - MSX2 (Aftermarket)": "msx2",
    "Microsoft - MSX2 [T-En] Collection": "msx2",
    "Microsoft - XBOX 360 [T-En] Collection": "xbox360",
    "Microsoft - XBOX [T-En] Collection": "xbox",
    "Microsoft - Xbox": "xbox",
    "Microsoft - Xbox (Development Kit Hard Drives)": "xbox",
    "Microsoft - Xbox - BIOS Images": "xbox",
    "Microsoft - Xbox - BIOS Images (DoM Version)": "xbox",
    "Microsoft - Xbox 360": "xbox360",
    "Microsoft - Xbox 360 (Development Kit Hard Drives)": "xbox360",
    "Microsoft - Xbox 360 (Digital)": "xbox360",
    "Milton-Bradley - Omni (Waveform)": "milton-bradley-omni",
    "Mobile - J2ME": "j2me",
    "Mobile - J2ME [T-En] Collection": "j2me",
    "Mobile - Palm OS": "palm-os",
    "Mobile - Palm OS (Digital)": "palm-os",
    "Mobile - Pocket PC": "pocket-pc",
    "Mobile - Pocket PC (Digital)": "pocket-pc",
    "Mobile - Symbian": "symbian",
    "NEC - PC Engine - TurboGrafx-16": "pc-engine",
    "NEC - PC Engine - TurboGrafx-16 (Aftermarket)": "pc-engine",
    "NEC - PC Engine - TurboGrafx-16 (Private)": "pc-engine",
    "NEC - PC Engine CD & TurboGrafx CD": "pc-engine-cd",
    "NEC - PC Engine CD [T-En] Collection": "pc-engine-cd",
    "NEC - PC Engine SuperGrafx": "supergrafx",
    "NEC - PC Engine SuperGrafx (Aftermarket)": "supergrafx",
    "NEC - PC Engine [T-En] Collection": "pc-engine",
    "NEC - PC-6001 [T-En] Collection": "pc-6001",
    "NEC - PC-8001 [T-En] Collection": "pc-88",
    "NEC - PC-88 (Flux)": "pc-88",
    "NEC - PC-88 (KryoFlux)": "pc-88",
    "NEC - PC-88 series": "pc-88",
    "NEC - PC-8801 [T-En] Collection": "pc-88",
    "NEC - PC-98": "pc-98",
    "NEC - PC-98 (Flux)": "pc-98",
    "NEC - PC-98 (Greaseweazle)": "pc-98",
    "NEC - PC-98 (HardDisk)": "pc-98",
    "NEC - PC-98 (Uncategorized)": "pc-98",
    "NEC - PC-98 series": "pc-98",
    "NEC - PC-9801 [T-En] Collection": "pc-98",
    "NEC - PC-FX & PC-FXGA": "pc-fx",
    "NEC - PC-FX [T-En] Collection": "pc-fx",
    "Namco-Sega-Nintendo": "arcade",
    "Navisoft - Naviken 2.1": "naviken-2-1",
    "Nichibutsu - My Vision": "my-vision",
    "Nichibutsu - My Vision (Mame)": "my-vision",
    "Nintendo - Famicom [T-En] Collection": "nes",
    "Nintendo - Family BASIC (Tapes)": "nes",
    "Nintendo - Family Computer Disk System (FDS)": "famicom-disk-system",
    "Nintendo - Family Computer Disk System (FDS) (Aftermarket)": "famicom-disk-system",
    "Nintendo - Family Computer Disk System (QD)": "famicom-disk-system",
    "Nintendo - Family Computer Disk System [T-En] Collection": "famicom-disk-system",
    "Nintendo - Family Computer Network System": "nes",
    "Nintendo - Game & Watch": "game-and-watch",
    "Nintendo - Game Boy": "gb",
    "Nintendo - Game Boy (Aftermarket)": "gb",
    "Nintendo - Game Boy (Private)": "gb",
    "Nintendo - Game Boy Advance": "gba",
    "Nintendo - Game Boy Advance (Aftermarket)": "gba",
    "Nintendo - Game Boy Advance (Multiboot)": "gba",
    "Nintendo - Game Boy Advance (Play-Yan)": "gba",
    "Nintendo - Game Boy Advance (Private)": "gba",
    "Nintendo - Game Boy Advance (Video)": "gba",
    "Nintendo - Game Boy Advance (Video) (Aftermarket)": "gba",
    "Nintendo - Game Boy Advance (Video) (Private)": "gba",
    "Nintendo - Game Boy Advance (e-Reader)": "gba",
    "Nintendo - Game Boy Advance (e-Reader) (Aftermarket)": "gba",
    "Nintendo - Game Boy Advance [T-En] Collection": "gba",
    "Nintendo - Game Boy Color": "gbc",
    "Nintendo - Game Boy Color (Aftermarket)": "gbc",
    "Nintendo - Game Boy Color (Private)": "gbc",
    "Nintendo - Game Boy Color [T-En] Collection": "gbc",
    "Nintendo - Game Boy [T-En] Collection": "gb",
    "Nintendo - GameCube - BIOS Images": "ngc",
    "Nintendo - GameCube - BIOS Images (DoM Version)": "ngc",
    "Nintendo - GameCube - NKit RVZ [zstd-19-128k]": "ngc",
    "Nintendo - GameCube [T-En] Collection": "ngc",
    "Nintendo - Kiosk Video Compact Flash (CardImage)": "nds",
    "Nintendo - Kiosk Video Compact Flash (Extracted)": "nds",
    "Nintendo - Misc": "nes",
    "Nintendo - New Nintendo 3DS (Decrypted)": "3ds",
    "Nintendo - New Nintendo 3DS (Digital) (Deprecated)": "3ds",
    "Nintendo - New Nintendo 3DS (Encrypted)": "3ds",
    "Nintendo - Nintendo 3DS (Decrypted)": "3ds",
    "Nintendo - Nintendo 3DS (Digital) (CDN)": "3ds",
    "Nintendo - Nintendo 3DS (Digital) (Deprecated)": "3ds",
    "Nintendo - Nintendo 3DS (Digital) (Dev ROMs)": "3ds",
    "Nintendo - Nintendo 3DS (Digital) (Pre-Install)": "3ds",
    "Nintendo - Nintendo 3DS (Digital) (SpotPass)": "3ds",
    "Nintendo - Nintendo 3DS (Encrypted)": "3ds",
    "Nintendo - Nintendo 3DS [T-En] Collection": "3ds",
    "Nintendo - Nintendo 64 (BigEndian)": "n64",
    "Nintendo - Nintendo 64 (BigEndian) (Aftermarket)": "n64",
    "Nintendo - Nintendo 64 (BigEndian) (Private)": "n64",
    "Nintendo - Nintendo 64 (ByteSwapped)": "n64",
    "Nintendo - Nintendo 64 (ByteSwapped) (Aftermarket)": "n64",
    "Nintendo - Nintendo 64 (ByteSwapped) (Private)": "n64",
    "Nintendo - Nintendo 64 (Mario no Photopi SmartMedia)": "n64",
    "Nintendo - Nintendo 64 [T-En] Collection": "n64",
    "Nintendo - Nintendo 64DD": "n64dd",
    "Nintendo - Nintendo 64DD [T-En] Collection": "n64dd",
    "Nintendo - Nintendo DS (DSvision SD cards)": "nds",
    "Nintendo - Nintendo DS (Decrypted)": "nds",
    "Nintendo - Nintendo DS (Decrypted) (Aftermarket)": "nds",
    "Nintendo - Nintendo DS (Decrypted) (Private)": "nds",
    "Nintendo - Nintendo DS (Download Play)": "nds",
    "Nintendo - Nintendo DS (Encrypted)": "nds",
    "Nintendo - Nintendo DS (Encrypted) (Aftermarket)": "nds",
    "Nintendo - Nintendo DS (Encrypted) (Private)": "nds",
    "Nintendo - Nintendo DS [T-En] Collection": "nds",
    "Nintendo - Nintendo DSi (Decrypted)": "dsi",
    "Nintendo - Nintendo DSi (Digital)": "dsi",
    "Nintendo - Nintendo DSi (Digital) (CDN) (Decrypted)": "dsi",
    "Nintendo - Nintendo DSi (Digital) (CDN) (Encrypted)": "dsi",
    "Nintendo - Nintendo DSi (Encrypted)": "dsi",
    "Nintendo - Nintendo DSi [T-En] Collection": "dsi",
    "Nintendo - Nintendo Entertainment System (Headered)": "nes",
    "Nintendo - Nintendo Entertainment System (Headered) (Aftermarket)": "nes",
    "Nintendo - Nintendo Entertainment System (Headered) (Private)": "nes",
    "Nintendo - Nintendo Entertainment System (Headerless)": "nes",
    "Nintendo - Nintendo Entertainment System (Headerless) (Aftermarket)": "nes",
    "Nintendo - Nintendo Entertainment System (Headerless) (Private)": "nes",
    "Nintendo - Nintendo GameCube (Memory Card)": "ngc",
    "Nintendo - Nintendo GameCube (NPDP Carts)": "ngc",
    "Nintendo - Nintendo Music (M4A)": "nintendo-music",
    "Nintendo - Nintendo Music (Tracks)": "nintendo-music",
    "Nintendo - Pokemon Mini": "pokemon-mini",
    "Nintendo - Pokemon Mini (Aftermarket)": "pokemon-mini",
    "Nintendo - Pokemon Mini [T-En] Collection": "pokemon-mini",
    "Nintendo - SDKs": "nes",
    "Nintendo - Satellaview": "satellaview",
    "Nintendo - Satellaview (Aftermarket)": "satellaview",
    "Nintendo - Sufami Turbo": "sufami-turbo",
    "Nintendo - Super Famicom - Enhanced Colors": "snes",
    "Nintendo - Super Famicom - MSU1": "snes",
    "Nintendo - Super Famicom - MSU1 [roms only]": "snes",
    "Nintendo - Super Famicom - Speed Hacks": "snes",
    "Nintendo - Super Famicom [T-En] Collection": "snes",
    "Nintendo - Super Nintendo Entertainment System": "snes",
    "Nintendo - Super Nintendo Entertainment System (Aftermarket)": "snes",
    "Nintendo - Super Nintendo Entertainment System (Private)": "snes",
    "Nintendo - Virtual Boy": "virtual-boy",
    "Nintendo - Virtual Boy (Aftermarket)": "virtual-boy",
    "Nintendo - Virtual Boy (Private)": "virtual-boy",
    "Nintendo - Virtual Boy [T-En] Collection": "virtual-boy",
    "Nintendo - Wallpapers": "nintendo-wallpapers",
    "Nintendo - Wii (Development Kit Hard Drives)": "wii",
    "Nintendo - Wii (Digital) (CDN)": "wii",
    "Nintendo - Wii (Starlight Fun Center)": "wii",
    "Nintendo - Wii - NKit RVZ [zstd-19-128k]": "wii",
    "Nintendo - Wii U (Development Kit Hard Drives)": "wiiu",
    "Nintendo - Wii U (Digital) (CDN)": "wiiu",
    "Nintendo - Wii U (Digital) (CDN) (Dev)": "wiiu",
    "Nintendo - Wii U (Digital) (CDN) (Lotcheck)": "wiiu",
    "Nintendo - Wii U - Disc Keys": "wiiu",
    "Nintendo - Wii U - WUX": "wiiu",
    "Nintendo - Wii [T-En] Collection": "wii",
    "Nintendo - amiibo": "amiibo",
    "Nokia - N-Gage (WIP)": "n-gage",
    "Nokia - N-Gage [T-En] Collection": "n-gage",
    "Non-Redump - Apple-Bandai - Pippin": "pippin",
    "Non-Redump - Atari - Atari Jaguar CD": "jaguar",
    "Non-Redump - Capcom - Play System III": "cps3",
    "Non-Redump - Commodore - Amiga CD": "amiga",
    "Non-Redump - FuRyu & Omron - Purikura": "purikura",
    "Non-Redump - Hasbro - iON Educational Gaming System": "hasbro-ion",
    "Non-Redump - IBM - PC Compatible (Discs)": "pc",
    "Non-Redump - IBM - PC Compatible (Discs) (Hentai)": "pc",
    "Non-Redump - Konami - M2": "konami-m2",
    "Non-Redump - Konami - Python 2": "konami-python-2",
    "Non-Redump - Merit Megatouch": "merit-megatouch",
    "Non-Redump - Microsoft - Pocket PC": "pocket-pc",
    "Non-Redump - Microsoft - Xbox": "xbox",
    "Non-Redump - Microsoft - Xbox 360": "xbox360",
    "Non-Redump - NEC - PC Engine CD + TurboGrafx CD": "pc-engine-cd",
    "Non-Redump - NEC - PC Engine CD + TurboGrafx CD (Aftermarket)": "pc-engine-cd",
    "Non-Redump - NEC - PC-88": "pc-88",
    "Non-Redump - Namco - Purikura": "purikura",
    "Non-Redump - Nintendo - Nintendo GameCube": "ngc",
    "Non-Redump - Nintendo - Nintendo GameCube (Aftermarket)": "ngc",
    "Non-Redump - Nintendo - Nintendo GameCube (Private)": "ngc",
    "Non-Redump - Nintendo - Wii": "wii",
    "Non-Redump - Nintendo - Wii U": "wiiu",
    "Non-Redump - Panasonic - 3DO Interactive Multiplayer": "3do",
    "Non-Redump - Philips - CD-i": "philips-cdi",
    "Non-Redump - Philips - CD-i (Aftermarket)": "philips-cdi",
    "Non-Redump - Playmaji - Polymega": "polymega",
    "Non-Redump - Sega - ALLS": "sega-alls",
    "Non-Redump - Sega - Dreamcast": "dc",
    "Non-Redump - Sega - Dreamcast (Aftermarket)": "dc",
    "Non-Redump - Sega - Dreamcast (Private)": "dc",
    "Non-Redump - Sega - Nu": "sega-nu",
    "Non-Redump - Sega - Nu 1.1": "sega-nu",
    "Non-Redump - Sega - Nu 2": "sega-nu",
    "Non-Redump - Sega - Nu SX": "sega-nu",
    "Non-Redump - Sega - Sega Mega CD + Sega CD": "sega-cd",
    "Non-Redump - Sega - Sega Mega CD + Sega CD (Aftermarket)": "sega-cd",
    "Non-Redump - Sega - Sega Saturn": "saturn",
    "Non-Redump - Sega NAOMI Satellite Terminal PC": "naomi",
    "Non-Redump - Sharp - Zaurus": "sharp-zaurus",
    "Non-Redump - Sony - PlayStation": "ps",
    "Non-Redump - Sony - PlayStation 2": "ps2",
    "Non-Redump - Sony - PlayStation 3": "ps3",
    "Non-Redump - Sony - PlayStation Portable": "psp",
    "Non-Redump - Sony Electronic Book": "sony-electronic-book",
    "Non-Redump - VM Labs - NUON": "nuon",
    "Non-Redump - ZAPiT Games - Game Wave Family Entertainment System": "game-wave",
    "Oh! MZ": "sharp-mz",
    "Ouya - Ouya": "ouya",
    "Panasonic - 3DO Interactive Multiplayer": "3do",
    "Panasonic - 3DO Interactive Multiplayer [T-En] Collection": "3do",
    "Panasonic - M2": "3do",
    "Panic - Playdate (Catalog) (Decrypted)": "playdate",
    "Panic - Playdate (Catalog) (Encrypted)": "playdate",
    "Panic - Playdate (Various)": "playdate",
    "Panic - Playdate (itch.io)": "playdate",
    "Philips - CD-i": "philips-cdi",
    "Philips - Videopac+": "magnavox-odyssey-2",
    "Pocket PC": "pocket-pc",
    "Pravetz": "pravetz",
    "RA - 3DO Interactive Multiplayer": "3do",
    "RA - Amstrad CPC": "amstrad-cpc",
    "RA - Apple II": "apple-2",
    "RA - Arcade": "arcade",
    "RA - Arduboy": "arduboy",
    "RA - Atari 2600": "atari-2600",
    "RA - Atari 7800": "atari-7800",
    "RA - Atari Jaguar": "jaguar",
    "RA - Atari Jaguar CD": "jaguar",
    "RA - Atari Lynx": "lynx",
    "RA - Colecovision": "colecovision",
    "RA - Elektor TV Games Computer": "elektor-tv-games",
    "RA - Emerson Arcadia 2001": "arcadia-2001",
    "RA - Fairchild Channel F": "fairchild-channel-f",
    "RA - GCE Vectrex": "vectrex",
    "RA - Interton VC 4000": "interton-vc-4000",
    "RA - Magnavox Odyssey 2": "magnavox-odyssey-2",
    "RA - Mattel Intellivision": "intellivision",
    "RA - Mega Duck": "mega-duck",
    "RA - Microsoft MSX": "msx",
    "RA - NEC PC-8801": "pc-88",
    "RA - NEC PC-FX": "pc-fx",
    "RA - NEC TurboGrafx-16": "pc-engine",
    "RA - NEC TurboGrafx-CD": "pc-engine-cd",
    "RA - Nintendo 64": "n64",
    "RA - Nintendo DS": "nds",
    "RA - Nintendo DSi": "dsi",
    "RA - Nintendo Entertainment System": "nes",
    "RA - Nintendo Famicom Disk System": "famicom-disk-system",
    "RA - Nintendo Game Boy": "gb",
    "RA - Nintendo Game Boy Advance": "gba",
    "RA - Nintendo Game Boy Color": "gbc",
    "RA - Nintendo GameCube": "ngc",
    "RA - Nintendo Pokemon Mini": "pokemon-mini",
    "RA - Nintendo Virtual Boy": "virtual-boy",
    "RA - SNK Neo Geo CD": "neo-geo-cd",
    "RA - SNK NeoGeo Pocket": "ngp",
    "RA - Sega 32X": "sega-32x",
    "RA - Sega CD": "sega-cd",
    "RA - Sega Dreamcast": "dc",
    "RA - Sega Game Gear": "game-gear",
    "RA - Sega Genesis": "genesis-slash-megadrive",
    "RA - Sega Master System": "sms",
    "RA - Sega SG-1000": "sg-1000",
    "RA - Sega Saturn": "saturn",
    "RA - Sony PSP": "psp",
    "RA - Sony Playstation": "ps",
    "RA - Sony Playstation 2": "ps2",
    "RA - Super Nintendo Entertainment System": "snes",
    "RA - Uzebox": "uzebox",
    "RA - WASM-4": "wasm-4",
    "RA - Watara Supervision": "supervision",
    "RA - WonderSwan": "wonderswan",
    "RCA - Studio II": "rca-studio-ii",
    "Radio-86RK": "radio-86rk",
    "Robotron": "robotron",
    "SNK - Neo Geo CD": "neo-geo-cd",
    "SNK - Neo Geo CD [T-En] Collection": "neo-geo-cd",
    "SNK - NeoGeo Pocket": "ngp",
    "SNK - NeoGeo Pocket Color": "ngpc",
    "SNK - NeoGeo Pocket Color [T-En] Collection": "ngpc",
    "Sanyo - MBC-550 (Flux)": "sanyo-mbc-550",
    "Sega - 32X": "sega-32x",
    "Sega - 32X (Aftermarket)": "sega-32x",
    "Sega - 32X - MD+": "sega-32x",
    "Sega - 32X - MSU-MD": "sega-32x",
    "Sega - Beena": "sega-pico",
    "Sega - Dreamcast": "dc",
    "Sega - Dreamcast (Development Kit Hard Drives)": "dc",
    "Sega - Dreamcast (Visual Memory Unit)": "dc",
    "Sega - Dreamcast - GDI Files": "dc",
    "Sega - Dreamcast [T-En] Collection": "dc",
    "Sega - Game Gear": "game-gear",
    "Sega - Game Gear (Aftermarket)": "game-gear",
    "Sega - Game Gear [T-En] Collection": "game-gear",
    "Sega - Master System - Mark III": "sms",
    "Sega - Master System - Mark III (Aftermarket)": "sms",
    "Sega - Master System - Mark III (Private)": "sms",
    "Sega - Master System [T-En] Collection": "sms",
    "Sega - Mega CD & Sega CD": "sega-cd",
    "Sega - Mega CD Hacks": "sega-cd",
    "Sega - Mega CD [T-En] Collection": "sega-cd",
    "Sega - Mega Drive - Enhanced Colors": "genesis-slash-megadrive",
    "Sega - Mega Drive - Genesis": "genesis-slash-megadrive",
    "Sega - Mega Drive - Genesis (Aftermarket)": "genesis-slash-megadrive",
    "Sega - Mega Drive - Genesis (Private)": "genesis-slash-megadrive",
    "Sega - Mega Drive - MD+": "genesis-slash-megadrive",
    "Sega - Mega Drive - MSU-MD": "genesis-slash-megadrive",
    "Sega - Mega Drive - Mode 1 CD": "genesis-slash-megadrive",
    "Sega - Mega Drive [T-En] Collection": "genesis-slash-megadrive",
    "Sega - PICO": "sega-pico",
    "Sega - Prologue 21": "sega-prologue-21",
    "Sega - SG-1000": "sg-1000",
    "Sega - SG-1000 - SC-3000": "sg-1000",
    "Sega - SG-1000 - SC-3000 (Aftermarket)": "sg-1000",
    "Sega - SG-1000 [T-En] Collection": "sg-1000",
    "Sega - Saturn": "saturn",
    "Sega - Saturn [T-En] Collection": "saturn",
    "Seta - Aleck64 (BigEndian)": "aleck64",
    "Seta - Aleck64 (ByteSwapped)": "aleck64",
    "Sharp - MZ-2200 (Waveform)": "sharp-mz-2200",
    "Sharp - MZ-700 (Waveform)": "sharp-mz-700",
    "Sharp - X1 (Waveform)": "sharp-x1",
    "Sharp - X1 [T-En] Collection": "sharp-x1",
    "Sharp - X68000": "x68000",
    "Sharp - X68000 (Flux)": "x68000",
    "Sharp - X68000 [T-En] Collection": "x68000",
    "Sinclair - ZX Spectrum +3": "zx-spectrum",
    "Sony - PlayStation": "ps",
    "Sony - PlayStation (PS one Classics) (PSN)": "ps",
    "Sony - PlayStation - BIOS Images": "ps",
    "Sony - PlayStation - BIOS Images (DoM Version)": "ps",
    "Sony - PlayStation - SBI Subchannels": "ps",
    "Sony - PlayStation 2": "ps2",
    "Sony - PlayStation 2 - BIOS Images": "ps2",
    "Sony - PlayStation 2 [T-En] Collection": "ps2",
    "Sony - PlayStation 3": "ps3",
    "Sony - PlayStation 3 (Development Kit Hard Drives) (Decrypted)": "ps3",
    "Sony - PlayStation 3 (PSN) (Avatars)": "ps3",
    "Sony - PlayStation 3 (PSN) (Content)": "ps3",
    "Sony - PlayStation 3 (PSN) (DLC)": "ps3",
    "Sony - PlayStation 3 (PSN) (Themes)": "ps3",
    "Sony - PlayStation 3 (PSN) (Updates)": "ps3",
    "Sony - PlayStation 3 - Disc Keys": "ps3",
    "Sony - PlayStation 3 - Disc Keys TXT": "ps3",
    "Sony - PlayStation 3 [T-En] Collection": "ps3",
    "Sony - PlayStation Mobile (PSN)": "psvita",
    "Sony - PlayStation Portable": "psp",
    "Sony - PlayStation Portable (PSN) (Decrypted)": "psp",
    "Sony - PlayStation Portable (PSN) (Encrypted)": "psp",
    "Sony - PlayStation Portable (PSN) (Minis) (Decrypted)": "psp",
    "Sony - PlayStation Portable (PSN) (Minis) (Encrypted)": "psp",
    "Sony - PlayStation Portable [T-En] Collection": "psp",
    "Sony - PlayStation Vita (PSN) (Content)": "psvita",
    "Sony - PlayStation Vita (PSN) (Updates)": "psvita",
    "Sony - PlayStation [T-En] Collection": "ps",
    "Source Code - Apple - II": "apple-2",
    "Source Code - Apple - IIGS": "apple-iigs",
    "Source Code - Arcade": "arcade",
    "Source Code - Atari - 2600": "atari-2600",
    "Source Code - Atari - 8-bit Family": "atari-800",
    "Source Code - Atari - Atari 2600 (Aftermarket)": "atari-2600",
    "Source Code - IBM - PC and Compatibles": "pc",
    "Source Code - Mobile - Palm OS": "palm-os",
    "Source Code - Nintendo - Game Boy Advance": "gba",
    "Source Code - Nintendo - Game Boy Color": "gbc",
    "Source Code - Nintendo - Nintendo - Game Boy Color": "gbc",
    "Source Code - Nintendo - Nintendo DS": "nds",
    "Source Code - Nintendo - Nintendo Entertainment System": "nes",
    "Source Code - Nintendo - Nintendo GameCube": "ngc",
    "Source Code - Nintendo - Super Nintendo Entertainment System": "snes",
    "Source Code - Panasonic - 3DO Interactive Multiplayer": "3do",
    "Source Code - Panasonic - M2": "3do",
    "Source Code - Sega - DreamCast": "dc",
    "Source Code - VM Labs - NUON": "nuon",
    "Source Code - Various": "pc",
    "TEMP IBM - PC and Compatibles (Digital) (Games for Windows Marketplace)": "pc",
    "TRQ": "trq",
    "Tatung": "tatung",
    "TeleNova - Compis (Flux)": "compis",
    "Tesla": "tesla-computer",
    "Texas Instruments - TI-99-4A (A2R)": "ti-99-4a",
    "Tiger - Game.com": "game-com",
    "Tiger - Gizmondo": "gizmondo",
    "Tomy - Kiss-Site": "tomy-kiss-site",
    "Toshiba - Pasopia (BIN)": "toshiba-pasopia",
    "Toshiba - Pasopia (WAV)": "toshiba-pasopia",
    "Toshiba - Visicom": "toshiba-visicom",
    "Triumph-Adler": "triumph-adler",
    "Tsukuda Original": "tsukuda-original",
    "Unofficial - Microsoft - Xbox 360 (Title Updates)": "xbox360",
    "Unofficial - Nintendo - Nintendo 3DS (Digital) (Updates and DLC) (Decrypted)": "3ds",
    "Unofficial - Nintendo - Nintendo 3DS (Digital) (Updates and DLC) (Encrypted)": "3ds",
    "Unofficial - Nintendo - Wii (Digital) (Deprecated) (WAD)": "wii",
    "Unofficial - Nintendo - Wii (Digital) (Split DLC) (Deprecated) (WAD)": "wii",
    "Unofficial - Nintendo - Wii U (Digital) (Deprecated)": "wiiu",
    "Unofficial - Sony - PlayStation 3 (BD-Video Extras)": "ps3",
    "Unofficial - Sony - PlayStation 3 (PSN) (Decrypted)": "ps3",
    "Unofficial - Sony - PlayStation Portable (PSN) (Decrypted)": "psp",
    "Unofficial - Sony - PlayStation Portable (PSX2PSP)": "psp",
    "Unofficial - Sony - PlayStation Portable (UMD Music)": "psp",
    "Unofficial - Sony - PlayStation Portable (UMD Video)": "psp",
    "Unofficial - Sony - PlayStation Vita (BlackFinPSV)": "psvita",
    "Unofficial - Sony - PlayStation Vita (NoNpDrm)": "psvita",
    "Unofficial - Sony - PlayStation Vita (PSN) (Decrypted) (NoNpDrm)": "psvita",
    "Unofficial - Sony - PlayStation Vita (PSN) (Decrypted) (VPK)": "psvita",
    "Unofficial - Sony - PlayStation Vita (PSVgameSD)": "psvita",
    "Unofficial - Sony - PlayStation Vita (VPK)": "psvita",
    "VM Labs - NUON": "nuon",
    "VM Labs - NUON (Digital)": "nuon",
    "VTech - CreatiVision": "vtech-creativision",
    "VTech - V.Flash & V.Smile Pro": "vtech-v-flash",
    "VTech - V.Smile": "vtech-v-smile",
    "Watara - Supervision": "supervision",
    "Watara - Supervision (Aftermarket)": "supervision",
    "Watara - Supervision (Private)": "supervision",
    "Welback - Mega Duck": "mega-duck",
    "Welback - Mega Duck (Aftermarket)": "mega-duck",
    "Yamaha - Copera": "yamaha-copera",
    "ZAPiT Games - Game Wave Family Entertainment System": "game-wave",
    "Zeebo - Zeebo": "zeebo",
    "Zeebo - Zeebo [T-En] Collection": "zeebo",
    "iQue - iQue (CDN)": "ique",
    "iQue - iQue (Decrypted)": "ique",
}



def _romm_destination(output_root: Path, system: str, basename: str) -> Path:
    """Build a RomM-compatible destination path.

    Falls back to ``system`` if no slug mapping exists.
    """
    slug = _SYSTEM_TO_ROMM_SLUG.get(system, system or "unknown")
    return output_root / slug / basename

# ── Scope-inference patterns ────────────────────────────────────────────────

_SCOPE_FILENAME_RE = re.compile(
    r"\((?P<collection>[^)]+)\)\s*-\s*(?P<system>[^)]+)",
    re.IGNORECASE,
)

_SCOPE_PATH_RE = re.compile(
    r"(?P<collection>redump|no-intro|trurip|fb|goodsets|mame)"
    r"[ /_-]+"
    r"(?P<system>[A-Za-z0-9 .'&!()-]+)",
    re.IGNORECASE,
)

_KNOWN_SYSTEMS: set[str] = {
    "sony", "playstation", "ps1", "ps2", "psp", "ps3", "ps4", "ps5",
    "nintendo", "nes", "snes", "n64", "gamecube", "wii", "wii u",
    "switch", "game boy", "gba", "gbc", "gb", "nds", "3ds",
    "sega", "genesis", "megadrive", "dreamcast", "saturn", "game gear",
    "master system", "sega cd", "32x",
    "microsoft", "xbox", "xbox 360", "xbox one", "xbox series",
    "atari", "2600", "5200", "7800", "jaguar", "lynx",
    "nec", "pc engine", "turbografx", "pc-fx",
    "snk", "neo geo", "ngpc", "ngcd",
    "panasonic", "3do",
    "bandai", "wonderswan",
    "commodore", "c64", "amiga",
    "dos", "ms-dos", "pc", "windows",
    "arcade", "mame",
    "nokia", "ngage",
    "sinclair", "zx spectrum",
    "mattel", "intellivision",
}

_CSV_SYSTEM_COLS = frozenset({"system", "platform", "console"})
_CSV_COLLECTION_COLS = frozenset({"collection", "set", "dat"})


def _infer_scope_from_csv(path: Path) -> ReportScope | None:
    """Try to infer scope from CSV column values."""
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = [ln for ln in text.split("\n") if ln.strip()]
    if not lines:
        return None
    header = lines[0].lower().split(",")
    sys_col = next((i for i, c in enumerate(header) if c.strip() in _CSV_SYSTEM_COLS), None)
    coll_col = next((i for i, c in enumerate(header) if c.strip() in _CSV_COLLECTION_COLS), None)
    if sys_col is None and coll_col is None:
        return None
    collection: str | None = None
    system: str | None = None
    for line in lines[1:]:
        parts = line.split(",")
        if sys_col is not None and sys_col < len(parts):
            val = parts[sys_col].strip().strip("\"'")
            if val:
                system = val
        if coll_col is not None and coll_col < len(parts):
            val = parts[coll_col].strip().strip("\"'")
            if val:
                collection = val
        if collection and system:
            break
    if collection or system:
        return ReportScope(collection=collection, system=system)
    return None


def _infer_scope_from_path(path: Path) -> ReportScope | None:
    """Try to infer scope from the file or directory path."""
    # Check the full parent path as a string (covers "redump/system/..." layouts)
    m = _SCOPE_PATH_RE.search(str(path.parent))
    if m:
        return ReportScope(
            collection=m.group("collection").title(),
            system=m.group("system").strip(),
        )
    # Check filename
    m = _SCOPE_PATH_RE.search(path.stem)
    if m:
        return ReportScope(
            collection=m.group("collection").title(),
            system=m.group("system").strip(),
        )
    return None


def _infer_scope_from_filename(filename: str) -> ReportScope | None:
    """Try to infer scope from the report filename pattern."""
    m = _SCOPE_FILENAME_RE.search(filename)
    if m:
        return ReportScope(
            collection=m.group("collection").strip(),
            system=m.group("system").strip(),
        )
    return None


def _infer_scope_from_distribution(
    entries: list[DatEntry],
    db: MinervaDB | None = None,
) -> ReportScope | None:
    """Try to infer scope by matching all entries and checking candidate distribution.

    If all top candidates share a single (collection, system) pair, use that.
    """
    _db = db or MinervaDB()
    scopes: dict[tuple[str | None, str | None], int] = {}
    for entry in entries[:20]:  # Sample first 20 entries
        best, _second = _db.get_two_best_candidates(entry)
        if best is not None:
            key = (best["collection"], best["system"])
            scopes[key] = scopes.get(key, 0) + 1
    if not scopes:
        return None
    # If a single scope accounts for >=80% of sampled matches, use it
    total = sum(scopes.values())
    for (coll, sys_name), count in scopes.items():
        if count / total >= 0.8:
            return ReportScope(collection=coll, system=sys_name)
    return None


# ── Service ──────────────────────────────────────────────────────────────────


class ReportAcquisitionService:
    """Single source of truth for report → queue workflow.

    Owns: scope inference, classification, queue construction, duplicate
    exclusion, destination generation, status updates.
    """

    def __init__(
        self,
        *,
        db: MinervaDB | None = None,
        state: MinervaState | None = None,
        policy: MatchPolicy = MatchPolicy(),
        download_controller: object | None = None,
        romresolve_policy: object | None = None,
    ) -> None:
        self._db = db or MinervaDB()
        self._state = state or MinervaState()
        self._policy = policy
        self._download_controller = download_controller
        if romresolve_policy is not None:
            self._romresolve_policy = romresolve_policy
        else:
            self._romresolve_policy = self._auto_load_romresolve_policy()

    @staticmethod
    def _auto_load_romresolve_policy() -> object | None:
        """Try to load a romresolve policy from known locations."""
        import importlib

        try:
            from romresolve.policy import load_policy
        except ImportError:
            return None

        from pathlib import Path

        candidates = [
            Path(".romresolve/policies/policy.translated-en.yaml"),
            Path("romresolve/examples/policy.translated-en.yaml"),
        ]
        # Try relative to the romresolve package
        try:
            mod = importlib.import_module("romresolve")
            pkg_root = Path(mod.__file__).resolve().parent.parent.parent
            candidates.append(pkg_root / "examples" / "policy.translated-en.yaml")
        except Exception:
            pass

        for path in candidates:
            if path.is_file():
                try:
                    p = load_policy(path)
                    log.info("Auto-loaded romresolve policy: %s from %s", p.profile_name, path)
                    return p
                except Exception:
                    continue

        # Fallback: build a default in code
        try:
            from romresolve.policy import PolicyDocument

            p = PolicyDocument(
                schema=1,
                profile_id="default",
                profile_name="Default (auto)",
                extends=None,
                languages_preferred=("en",),
                languages_fallback=("en",),
                require_full_translation=False,
                regions_order=("World", "USA", "Europe", "Japan"),
                prefer_ntsc=True,
                content_exclude=("demo", "sample", "kiosk", "preview", "trade_demo", "beta", "prototype", "aftermarket"),
                preproduction=tuple(),
                replace_untranslated_original=False,
                allow_partial=True,
                prefer_latest_stable=True,
                enhancements=tuple(),
            )
            log.info("Using built-in default romresolve policy")
            return p
        except Exception:
            return None

    # ── Scope inference ───────────────────────────────────────────────────

    def infer_scope(self, path: Path) -> ReportScope:
        """Infer report scope from the file.  Raises ScopeInferenceRequired
        if no scope can be determined.
        """
        # 1. CSV columns
        if path.suffix.lower() == ".csv":
            scope = _infer_scope_from_csv(path)
            if scope is not None:
                return scope

        # 2. Path regex
        scope = _infer_scope_from_path(path)
        if scope is not None:
            return scope

        # 3. Filename pattern
        scope = _infer_scope_from_filename(path.stem)
        if scope is not None:
            return scope

        # 4. Candidate distribution — needs to parse entries first
        info = (
            parse_rv_fix_csv(path)
            if path.suffix.lower() == ".csv"
            else parse_dat_file(path)
        )
        if info.entries:
            scope = _infer_scope_from_distribution(list(info.entries), db=self._db)
            if scope is not None:
                return scope
            # 5. Raise with candidates
            db = self._db or MinervaDB()
            observed: dict[tuple[str | None, str | None], int] = {}
            for entry in info.entries[:30]:
                best, _second = db.get_two_best_candidates(entry)
                if best is not None:
                    key = (best["collection"], best["system"])
                    observed[key] = observed.get(key, 0) + 1
            candidates = sorted(
                [(c, s, count) for (c, s), count in observed.items()],
                key=lambda x: -x[2],
            )[:5]
            if candidates:
                raise ScopeInferenceRequired(candidates)

        raise ScopeInferenceRequired([])

    # ── Import ─────────────────────────────────────────────────────────────

    def import_report(
        self,
        path: Path,
        scope: ReportScope | None = None,
    ) -> ReportSummary:
        """Parse the file, infer scope, persist the report.

        If scope is None and inference is ambiguous, raise
        ScopeInferenceRequired carrying the candidates so the page
        can prompt once.
        """
        info = (
            parse_rv_fix_csv(path)
            if path.suffix.lower() == ".csv"
            else parse_dat_file(path)
        )
        if not info.entries:
            raise ValueError(f"Empty report: {path}")

        # Resolve scope
        resolved_scope = scope
        if resolved_scope is None:
            resolved_scope = self.infer_scope(path)

        existing = self._state.get_report_by_path(path)
        report_id = existing.id if existing else uuid.uuid4().hex

        report = ReportSummary(
            id=report_id,
            path=str(path),
            name=info.name or path.stem,
            collection=resolved_scope.collection if resolved_scope else info.collection,
            system=resolved_scope.system if resolved_scope else info.system,
            imported_at=datetime.now(timezone.utc).isoformat(),
            requested_count=len(info.entries),
            status="draft",
        )

        if existing:
            self._state.update_report(
                report.id,
                path=report.path,
                name=report.name,
                collection=report.collection,
                system=report.system,
                requested_count=report.requested_count,
                status="draft",
            )
        else:
            self._state.save_report(report)

        self._state.add_event(
            "import",
            f"Imported report {report.name} ({len(info.entries)} entries)",
        )
        return report

    # ── Matching ───────────────────────────────────────────────────────────

    def _classify(
        self,
        entry: DatEntry,
        scope: ReportScope | None,
        policy: MatchPolicy,
    ) -> tuple[ResolutionState, int | None, str | None, float | None]:
        """Classify a single entry using margin-based classification.

        Returns (resolution, file_id, method, confidence).
        """
        collection = scope.collection or ""
        system = scope.system or ""

        best, second = self._db.get_two_best_candidates(
            entry, collection=collection, system=system,
        )

        # No candidate
        if best is None:
            return ResolutionState.NOT_FOUND, None, None, None

        # Below absolute confidence floor
        if best["confidence"] < 0.5:
            return ResolutionState.NOT_FOUND, best["file_id"], best["method"], best["confidence"]

        # Cross-system guard
        if policy.require_same_collection and collection:
            if best["collection"] != collection:
                return ResolutionState.NOT_FOUND, best["file_id"], best["method"], best["confidence"]
        if policy.require_same_system and system:
            if best["system"] != system:
                # When scope's system is known, a different-system candidate is NOT_FOUND
                return ResolutionState.NOT_FOUND, best["file_id"], best["method"], best["confidence"]

        # Exact match auto-accept
        if best["method"] == "exact" and policy.auto_accept_exact:
            return ResolutionState.READY, best["file_id"], best["method"], best["confidence"]

        # Margin-based fuzzy classification
        if best["confidence"] >= policy.fuzzy_min_confidence:
            if second is None or (best["confidence"] - second["confidence"]) >= policy.fuzzy_min_margin:
                return ResolutionState.READY, best["file_id"], best["method"], best["confidence"]

        # Everything else needs review
        return ResolutionState.REVIEW_REQUIRED, best["file_id"], best["method"], best["confidence"]

    def _try_romresolve(
        self,
        dat_entry: DatEntry,
        scope: ReportScope | None,
    ) -> int | None:
        """Try romresolve region/content scoring to disambiguate candidates.

        Returns the best file_id, or None if romresolve can't help.
        """
        if self._romresolve_policy is None:
            return None

        from romresolve.minerva import CandidateInfo, score_candidates

        collection = scope.collection or "" if scope else ""
        system = scope.system or "" if scope else ""

        detailed = self._db.match_dat_detailed(
            [dat_entry], collection=collection, system=system,
            candidate_limit=10,
        )

        if not detailed.get("results"):
            return None

        per_entry = detailed["results"][0]
        scored = per_entry.get("candidates", [])

        if not scored:
            return None

        if len(scored) == 1:
            return scored[0]["file_id"]

        candidates = [
            CandidateInfo(file_id=c["file_id"], basename=c["title"])
            for c in scored
        ]
        file_ids = [c.file_id for c in candidates]
        regions = self._db.get_file_regions(file_ids)
        tags = self._db.get_file_tags(file_ids)

        return score_candidates(candidates, regions, tags, self._romresolve_policy)

    def match_report(
        self,
        report_id: str,
        policy: MatchPolicy | None = None,
    ) -> AcquisitionSummary:
        """Run the matcher on every entry, classify by resolution, persist.

        Returns counts.  Uses replace_entries internally.
        """
        report = self._state.get_report(report_id)
        if report is None:
            raise ValueError(f"Report not found: {report_id}")

        policy = policy or self._policy
        scope = ReportScope(
            collection=report.collection,
            system=report.system,
        )

        # Load the original entries from the report file (or state for JSON)
        path = Path(report.path)
        clean_name = path.name.split("#")[0]
        if clean_name.lower().endswith(".json"):
            saved = self._state.get_entries(report_id)
            dat_entries = [
                DatEntry(filename=e.filename, size=e.size)
                for e in saved
            ]
        else:
            info = (
                parse_rv_fix_csv(path)
                if path.suffix.lower() == ".csv"
                else parse_dat_file(path)
            )
            dat_entries = list(info.entries)

        entries: list[ReviewEntry] = []
        counts = AcquisitionSummary()

        for ordinal, dat_entry in enumerate(dat_entries):
            resolution, file_id, method, confidence = self._classify(
                dat_entry, scope, policy,
            )

            if resolution == ResolutionState.REVIEW_REQUIRED:
                romresolve_id = self._try_romresolve(dat_entry, scope)
                if romresolve_id is not None:
                    resolution = ResolutionState.READY
                    file_id = romresolve_id
                    method = "romresolve"
                    confidence = 1.0

            # Map resolution → decision for backward compat
            if resolution == ResolutionState.READY:
                decision = "accept"
            elif resolution == ResolutionState.REVIEW_REQUIRED:
                decision = "pending"
            elif resolution == ResolutionState.NOT_FOUND:
                decision = "reject"
            else:
                decision = "reject"

            # Update counts
            if resolution == ResolutionState.READY:
                counts = AcquisitionSummary(
                    ready=counts.ready + 1,
                    review_required=counts.review_required,
                    not_found=counts.not_found,
                    ignored=counts.ignored,
                )
            elif resolution == ResolutionState.REVIEW_REQUIRED:
                counts = AcquisitionSummary(
                    ready=counts.ready,
                    review_required=counts.review_required + 1,
                    not_found=counts.not_found,
                    ignored=counts.ignored,
                )
            elif resolution == ResolutionState.NOT_FOUND:
                counts = AcquisitionSummary(
                    ready=counts.ready,
                    review_required=counts.review_required,
                    not_found=counts.not_found + 1,
                    ignored=counts.ignored,
                )

            entries.append(ReviewEntry(
                id=f"{report_id}_{ordinal}",
                report_id=report_id,
                ordinal=ordinal,
                filename=dat_entry.filename,
                size=dat_entry.size,
                automatic_file_id=file_id,
                automatic_method=method,
                automatic_confidence=confidence,
                resolution=resolution,
                decision=decision,
            ))

        # Atomically replace entries
        self._state.replace_entries(report_id, entries)

        # Update report summary (map to legacy DB column names)
        self._state.update_report(
            report_id,
            matched_count=counts.ready,
            fuzzy_count=counts.review_required,
            unmatched_count=counts.not_found,
            status="ready",
        )

        self._state.add_event(
            "match",
            f"Matched report {report_id}: {counts.ready} ready, "
            f"{counts.review_required} review, {counts.not_found} not found",
        )

        return counts

    # ── Queue construction ─────────────────────────────────────────────────

    def queue_ready(
        self,
        report_id: str,
        *,
        include_reviewed: bool = True,
    ) -> QueueResult:
        """Build queue records for every READY (and optionally reviewed) entry.

        Idempotent — skips entries already in the active/queued/completed
        state. Routes through the download controller when one is
        available so the controller can emit ``queue_changed`` and
        schedule qBittorrent submission.
        """
        entries = self._state.get_entries(report_id)
        if not entries:
            return QueueResult(added=0, skipped_active=0, skipped_complete=0, skipped_missing=0)

        # Gather ready and/or reviewed entries
        queueable: list[ReviewEntry] = []
        for entry in entries:
            if entry.resolution == ResolutionState.NOT_FOUND:
                continue
            if entry.resolution == ResolutionState.READY:
                queueable.append(entry)
            elif include_reviewed and entry.decision == "accept":
                queueable.append(entry)

        if not queueable:
            return QueueResult(added=0, skipped_active=0, skipped_complete=0, skipped_missing=0)

        # Load existing queue state
        queue_records = self._state.list_queue()
        active_file_ids: set[int] = set()
        completed_file_ids: set[int] = set()
        for rec in queue_records:
            if rec.status in {"queued", "starting", "downloading", "paused", "seeding"}:
                active_file_ids.add(rec.file_id)
            elif rec.status in {"completed"}:
                completed_file_ids.add(rec.file_id)

        # Build queue records, skipping already-present entries
        output_root = Path("downloads")
        try:
            from PyQt6 import QtCore
            output_root = Path(
                QtCore.QSettings("MinervaFixDAT", "MinervaGUI").value(
                    "output_dir", "downloads", str,
                )
            )
        except Exception:
            pass

        db = self._db or MinervaDB()
        added = 0
        skipped_active = 0
        skipped_complete = 0
        skipped_missing = 0

        for entry in queueable:
            file_id = entry.selected_file_id or entry.automatic_file_id
            if file_id is None:
                skipped_missing += 1
                continue
            if file_id in active_file_ids:
                skipped_active += 1
                continue
            if file_id in completed_file_ids:
                skipped_complete += 1
                continue

            # Resolve destination
            item = db.get_files_by_ids([file_id])
            if not item:
                skipped_missing += 1
                continue
            destination = _romm_destination(output_root, item[0].system, item[0].basename)

            # Route through the download controller when available so
            # queue_changed fires and qBittorrent submission is
            # scheduled. Fall back to direct DB write otherwise.
            if self._download_controller is not None and hasattr(
                self._download_controller, "add_to_queue"
            ):
                record_id = self._download_controller.add_to_queue(
                    file_id, str(destination), entry.id,
                )
                self._state.update_entry_decision(entry.id, "accept", file_id)
                if record_id:
                    added += 1
            else:
                from minerva.domain.downloads import QueueRecord as QueueRecordType

                record_id = uuid.uuid4().hex
                now = datetime.now(timezone.utc).isoformat()
                record = QueueRecordType(
                    id=record_id,
                    file_id=file_id,
                    report_entry_id=entry.id,
                    status="queued",
                    destination=str(destination),
                    created_at=now,
                    updated_at=now,
                )
                self._state.save_queue_record(record)
                self._state.update_entry_decision(entry.id, "accept", file_id)
                added += 1

        # Emit change event
        self._state.add_event(
            "queue",
            f"Queued {added} ROMs from report {report_id}",
        )

        return QueueResult(
            added=added,
            skipped_active=skipped_active,
            skipped_complete=skipped_complete,
            skipped_missing=skipped_missing,
        )

    # ── Triage / outcome ───────────────────────────────────────────────────

    def compute_outcome(
        self,
        report_id: str,
        constraints: AcquisitionConstraints | None = None,
    ) -> ReportOutcome:
        """Compute the triage outcome for a report based on current state.

        Returns one of ``ReportOutcome`` values.
        """
        entries = self._state.get_entries(report_id)
        if not entries:
            return ReportOutcome.EMPTY

        safe = [e for e in entries if e.resolution == ResolutionState.READY]
        ambiguous = [e for e in entries if e.resolution == ResolutionState.REVIEW_REQUIRED]
        not_found = [e for e in entries if e.resolution == ResolutionState.NOT_FOUND]

        # Determine eligible entries by applying constraints
        eligible = self._filter_eligible(safe, constraints)

        if not eligible:
            if safe:
                return ReportOutcome.FILTERED_OUT
            if ambiguous:
                return ReportOutcome.NEEDS_REVIEW
            if not_found and not safe:
                return ReportOutcome.NO_SOURCE_MATCHES
            if self._all_already_present(report_id):
                return ReportOutcome.ALREADY_SATISFIED
            return ReportOutcome.EMPTY

        # Eligible entries exist — check if all are already completed
        if self._all_already_present(report_id):
            return ReportOutcome.ALREADY_SATISFIED

        return ReportOutcome.ACTIONABLE

    def _filter_eligible(
        self,
        safe_entries: list[ReviewEntry],
        constraints: AcquisitionConstraints | None,
    ) -> list[ReviewEntry]:
        """Filter safe entries by size constraints.

        Returns entries that pass all constraint checks.
        """
        if constraints is None:
            return safe_entries
        eligible: list[ReviewEntry] = []
        for entry in safe_entries:
            if constraints.max_file_bytes is not None and entry.size > constraints.max_file_bytes:
                continue
            # No collection/system/region filtering here — that requires
            # DB lookups and is done by the planner. The simple triage
            # check only filters by entry-level constraints.
            eligible.append(entry)
        return eligible

    def _all_already_present(self, report_id: str) -> bool:
        """Check if every entry in the report is already completed."""
        from minerva_db import MinervaDB

        entries = self._state.get_entries(report_id)
        if not entries:
            return False
        queue = self._state.list_queue()
        completed_ids: set[int] = set()
        for rec in queue:
            if rec.status in {"completed", "seeding"}:
                completed_ids.add(rec.file_id)
        for entry in entries:
            file_id = entry.selected_file_id or entry.automatic_file_id
            if file_id is not None and file_id not in completed_ids:
                return False
        return True

    # ── queue_plan ─────────────────────────────────────────────────────────

    def queue_plan(self, plan: AcquisitionPlan) -> QueueResult:
        """Atomically add every PlannedFile in the plan to the download queue.

        The plan is the exact set of records queued — no re-running of
        filters or scope inference at queue time. Routes through the
        download controller when one is available.
        """
        from minerva.domain.downloads import QueueRecord
        from datetime import datetime, timezone

        queue_records = self._state.list_queue()
        active_file_ids: set[int] = set()
        for rec in queue_records:
            if rec.status in {"completed", "queued", "starting", "downloading", "paused", "seeding"}:
                active_file_ids.add(rec.file_id)

        added = 0
        skipped_active = 0
        for pf in plan.selected:
            if pf.file_id in active_file_ids:
                skipped_active += 1
                continue

            if self._download_controller is not None and hasattr(
                self._download_controller, "add_to_queue"
            ):
                record_id = self._download_controller.add_to_queue(
                    pf.file_id, str(pf.destination), pf.report_entry_id,
                )
                self._state.update_entry_decision(pf.report_entry_id, "accept", pf.file_id)
                if record_id:
                    added += 1
            else:
                record_id = uuid.uuid4().hex
                now = datetime.now(timezone.utc).isoformat()
                record = QueueRecord(
                    id=record_id,
                    file_id=pf.file_id,
                    report_entry_id=pf.report_entry_id,
                    status="queued",
                    destination=str(pf.destination),
                    created_at=now,
                    updated_at=now,
                )
                self._state.save_queue_record(record)
                self._state.update_entry_decision(pf.report_entry_id, "accept", pf.file_id)
                added += 1

        self._state.add_event(
            "queue",
            f"Queued {added} ROMs from plan for {plan.report_id}",
        )

        return QueueResult(
            added=added,
            skipped_active=skipped_active,
            skipped_complete=0,
            skipped_missing=0,
        )

    # ── Rematch ────────────────────────────────────────────────────────────

    def rematch_report(
        self,
        report_id: str,
        policy: MatchPolicy | None = None,
    ) -> AcquisitionSummary:
        """Atomically replace entries and reclassify.

        Uses replace_entries() not save_entries().
        """
        return self.match_report(report_id, policy=policy)

    def queue_all_ready(
        self,
        *,
        name_filter: str = "",
        include_reviewed: bool = True,
    ) -> QueueResult:
        """Queue ready entries from every report matching the name filter.

        Iterates all reports (or those whose name contains *name_filter*)
        and calls ``queue_ready`` on each. Returns the aggregate result.
        """
        reports = self._state.list_reports()
        if name_filter:
            reports = [r for r in reports if name_filter in r.name]
        total = QueueResult(
            added=0, skipped_active=0, skipped_complete=0, skipped_missing=0,
        )
        for r in reports:
            sub = self.queue_ready(r.id, include_reviewed=include_reviewed)
            total = QueueResult(
                added=total.added + sub.added,
                skipped_active=total.skipped_active + sub.skipped_active,
                skipped_complete=total.skipped_complete + sub.skipped_complete,
                skipped_missing=total.skipped_missing + sub.skipped_missing,
            )
        return total
