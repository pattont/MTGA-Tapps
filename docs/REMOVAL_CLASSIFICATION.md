# Removal / Wipe / Bounce / Counter Classification

The Combat & Resources panel's interaction stats come from text-based
classification (`removal_classifier.py`): a card's role is what its rules
text says, decided once per card. This file is the decision ledger — what
was ruled, why, and what's still open. **When a game's numbers look wrong,
check the card against these rules first, then add a case to Open Questions
below and raise it for a ruling.**

## Decided rules

| Rule | Ruling | Decided |
| --- | --- | --- |
| Battlefield removal ("destroy/exile target creature/permanent/…") | **Removal** | original design |
| Land destruction (incl. "target nonbasic land") | **Not counted** (event-based lands-lost stat covers it) | original design |
| Graveyard/hand/library effects ("exile target card from a graveyard") | **Not removal** — battlefield removal never targets a "card" | 2026-08-29 |
| Edicts ("target opponent exiles/sacrifices a creature of their choice") | **Removal** (Strategic Betrayal, Tribute to Hunger, Pick Your Poison, Sothera) | 2026-08-29 (Travis) |
| State-qualified sweeps ("destroy all tapped/untapped/attacking creatures") | **Removal, not wipe** — Split Up usually kills half a board | 2026-08-29 (Travis) |
| Conditional sweepers (damage-to-each, mass -X/-X, type-qualified destruction: Fire Magic, Desolation of Smaug) | **Judged by outcome**: board actually cleared → wipe; any survivor → removal. Historical games (no outcome data) default to removal. | 2026-08-29 (Travis) |
| Unconditional wipes vs indestructible (Ultima) | **Still a wipe** — no toughness beats "destroy all"; the survivor just doesn't appear in Creatures Lost to Removal | 2026-08-29 (Travis) |
| Temporary exile / O-Ring shells ("exile target … until this leaves") | **Removal** (leans-yes; see open questions) | 2026-08-29 (Travis, provisional) |
| Self-blink ("exile target creature **you control** …") | **Not counted** — protecting your own permanent | 2026-08-29 |
| Airbend (Avatar set: exile, owner may recast for {2}) | **Bounce** on the battlefield reading | 2026-08-29 (Travis) |
| Mass bounce subsets (Aetherize "all attacking creatures") | **Bounce** | 2026-08-29 |
| Hand disruption ("target opponent exiles/discards a card from their hand") | **Not removal** | 2026-08-29 |
| Deathtouch reminder text ("enough to destroy it") | **Not counted** (reminder text never matches) | original design |

## Open questions

- **Temporary exile as its own category?** O-Ring effects count as removal
  today, but enchantment removal on the shell gives the card back free —
  arguably its own stat. (Travis, undecided.)
- **Airbend on the stack** acts as a counterspell, not bounce. Text-based
  classification can't split one card's roles by zone; airbend cards count
  as bounce regardless of how they were used.
- **Activated-ability interaction on permanents**: a card is counted when
  PLAYED, even if its removal is an activated ability that never fired
  (text-based design). Ugin's cast trigger makes this mostly right.
- **Conditional sweepers drawn but not played** have no outcome to judge —
  they count as removal-in-hand (the conservative default).
- **Outcome detection mechanics**: the tracker snapshots the battlefield's
  creatures when a conditional sweeper is cast and rules wipe-vs-removal at
  the next turn header (or game end). Blinked/phased creatures returning
  after the verdict aren't re-litigated.

## Current classification over this collection's card pool

Generated from Scryfall oracle text on 2026-08-29 (Arena text may differ
slightly; the tracker classifies from Arena's own ability text at runtime).

### Removal (224)

Aang's Iceberg, Abomination, Terrifying Titan, Abrade, Ajani, Outland Chaperone, Allies at Last, Archdruid's Charm, Archenemy's Charm, Assassin's Trophy, Assimilation Aegis, Auntie's Sentence, Aven Interrupter, Awaken the Honored Dead, Azog, Moria's Ruin, Azula, Cunning Usurper, Banishing Light, Battle Menu, Bear Trap, Bite Down, Bitter Triumph, Blooming Blast, Breeches, the Blastmaker, Broadside Barrage, Broken Wings, Bullseye, Death Dealer, Burn, Burn, Tree and Fern, Burst Lightning, Bushwhack, Candy Grapple, Cathar Commando, Caustic Exhale, Chainsaw, Chandra, Spark Hunter, Channeled Dragonfire, Chocobo Kick, Chomping Changeling, Coliseum Behemoth, Combustion Technique, Come Back Wrong, Cornered by Black Mages, Cruel Alliance, Curious Farm Animals, Dark Deed, Deadly Brew, Deadly Precision, Depower, Desperate Measures, Devourer of Destiny, Dimensional Exile, Disenchant, Disruptive Stormbrood, Dissection Practice, Drag to the Roots, Dragonbroods' Relic, Drakuseth, Maw of Flames, Dreadmaw's Ire, Dusk Rose Reliquary, Eaten Alive, Elspeth, Storm Slayer, Embrace Oblivion, Emergency Eject, Emeritus of Conflict, Emeritus of Truce, End of the Hunt, Epic Fight, Erode, Exorcise, Extraordinary Journey, Fanatical Firebrand, Feed the Cycle, Feed the Swarm, Fell, Final Vengeance, Firebending Lesson, Flick a Coin, Gatekeeper of Malakir, Get Lost, Go Nuts!, Grub's Command, Guerrilla Gorilla, HULK SMASH!, Hard-Hitting Question, Heartless Act, Heated Argument, Helicarrier Strike, Heritage Reclamation, Hero's Downfall, High Noon, Hour of Defeat, Hunter's Talent, Idol of the Deep King, Impractical Joke, Inevitable Defeat, Insidious Fungus, Jeskai Revelation, Kaervek, the Punisher, Kaya, Spirits' Justice, Killmonger, Scourge of Wakanda, Kozilek's Command, Kutzil's Flanker, Last Gasp, Leatherhead, Swamp Stalker, Legion Extruder, Lightning Bolt, Lightning Helix, Lightning Strike, Live or Die, Long Goodbye, Lorehold Charm, Maelstrom Pulse, Magnificent End, Make Your Move, Manhole Missile, Meltstrider's Resolve, Molten Collapse, Moment of Craving, Moment of Reckoning, Momentum Breaker, Mortify, Mouser Foundry, Mudbutton Cursetosser, Murder, Murdock's Crusade, Nova Hellkite, Obliterating Bolt, Oko, Lorwyn Liege, Origin of Metalbending, Overlord of the Boilerbilges, Parting Gust, Pawpatch Formation, Perilous Snare, Phoenix Down, Pick Your Poison, Pinecone Strike, Pit of Offerings, Plasma Bolt, Playful Shove, Price of Freedom, Primal Might, Professor Dellian Fel, Punishing Punch, Pyrrhic Strike, Quandrix Charm, Reclamation Sage, Red Guardian, Super-Soldier, Requisition Raid, Requiting Hex, Ride's End, Roaring Furnace, Ronin, Shadow Stalker, Rust Harvester, Ruthless Lawbringer, Scorching Dragonfire, Scorching Shot, Scrap Compactor, Scrapshooter, Seam Rip, Sear, Secret Invasion, Seedship Impact, Shattered Acolyte, She-Hulk, Jade Defender, Sheltered by Ghosts, Shiko, Paragon of the Way, Shock, Shoot the Sheriff, Shredder's Technique, Silverquill Charm, Slick Sequence, Smaug the Magnificent, Sonar Strike, Sothera, the Supervoid, Soul Enervation, Spectacular Tactics, Split Up, Spring-Loaded Sawblades, Stab, Stadium Headliner, Stasis Snare, Stormplain Detainment, Strategic Betrayal, Stroke of Midnight, Summon: Bahamut, Summon: Primal Odin, Super Villain Lockup, Super-Skrull, Suplex, Survey Mechan, Syr Vondam, Sunstar Exemplar, Territory Forge, Terror of the Peaks, The Coming of Galactus, The End, The Last Agni Kai, The Mighty Thor, Jane Foster, The Princess Takes Flight, The Ruinous Wrecking Crew, The Serpent Society, Thor, God of Thunder, Throne of the Grim Captain, Thunder Magic, Thundering Rebuke, Tithing Blade, Torch the Tower, Tragic Trajectory, Tribute to Hunger, Truck Toss, Trumpeting Carnosaur, Turncoat Kunoichi, Twinmaw Stormbrood, Ugin, Eye of the Storms, Urgent Necropsy, Vibrance, Vibrant Outburst, Virtue of Persistence, Vivien Reid, Weapons Manufacturing, Weather Maker, Web Up, White Auracite, Widow's Bite, Wistfulness, Witherbloom Charm, Withering Torment, Zuko's Exile

### Board wipes (27)

Amalia Benavides Aguirre, Ashling's Command, Avengers Disassembled, Avengers: Under Siege, Beyond the Quiet, Day of Judgment, Deadly Cover-Up, Desolation of Smaug, Dragonback Assault, Extinguisher Battleship, Fire Magic, Fumigate, Iroh's Demonstration, Mjölnir, Hammer of Thor, Pinnacle Starcage, Pyroclasm, Singularity Rupture, Slagstorm, Spectacular Pileup, Splatter Technique, Thanos, the Mad Titan, The Rise of Sozin, Ultima, Unstable Glyphbridge, Vicious Rivalry, Withering Curse, Zero Point Ballad

### Bounce (19)

Aang, Swift Savior, Aetherize, Airbender Ascension, Avatar's Wrath, Banishing Betrayal, Bilbo's Gambit, Boomerang Basics, Bottomless Pool, Bounce Off, Desculpting Blast, Into the Flood Maw, Into the Roil, Jeskai Revelation, Justice, Vance Astrovik, Nurturing Pixie, Prismari Charm, Scalding Viper, The Legend of Yangchen, Unsummon

### Counterspells (31)

Amazing Acrobatics, Annul, Armored Armadillo, Axebane Ferox, Cactusfolk Sureshot, Disdainful Stroke, Dispelling Exhale, Diversion Unit, Divert Disaster, Dragonfly Swarm, Dwarven Mattock, Flashfreeze, Fugitive Droid, Get Out, It'll Quench Ya!, Lavaspur Boots, Long River's Pull, Mana Sculpt, Negate, No More Lies, Phantom Interference, Quandrix Charm, Skyward Spider, Spell Pierce, Spell Snare, Spell Stutter, Spider-Sense, Super Strength, Syncopate, Three Steps Ahead, Titania, Rugged Rumbler

