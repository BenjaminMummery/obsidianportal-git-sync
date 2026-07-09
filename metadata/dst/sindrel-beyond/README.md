# Sindrel Beyond character sheet (Obsidian Portal DST)

Matches the **description HTML sheet** (`src/lore_bridge/dndbeyond/templates/sheet.html` + `metadata/ddb-sheet.css`): grey blockquote styling, div-only markup, save grid, combat buckets, conditional spellcasting. Features & Traits remain in **GM Only** (`game_master_info`), not here.

**Slug:** `sindrel_beyond` (installed campaign DST may show `sinbdrel_beyond` — JS handles both)  
**Game system:** D&D 5E

## Files

| File | Purpose |
|------|---------|
| `html_template.html` | OP DST HTML |
| `css.css` | OP DST CSS (scoped copy of `ddb-sheet.css`) |
| `javascript.js` | Avatar injection, collapsible spell cards, hide empty sections |
| `fields.yaml` | `dynamic_sheet` field contract |
| `sample-dynamic_sheet.json` | Test payload |

## Install / update on Obsidian Portal

1. Campaign game system → **D&D 5E**.
2. Edit your existing **Sindrel Beyond** DST (or [create new](https://www.obsidianportal.com/dynamic_sheet_templates)).
3. Paste updated `html_template.html`, `css.css`, `javascript.js`.
4. Save. Re-open a test PC to verify layout.

UUID for this campaign: `38274b74909343e1a3e95400091308c3`

Set on Render: `DYNAMIC_SHEET_TEMPLATE_ID=38274b74909343e1a3e95400091308c3`

## Lore repo

PC `.textile` frontmatter:

```yaml
dynamic_sheet_template_id: "38274b74909343e1a3e95400091308c3"
dndbeyond_id: "156087500"
dynamic_sheet:
  class_summary: "Paladin (Oath of Vengeance) 3"
  prof_bonus: "+2"
  # ... see fields.yaml
```

Run `lore-bridge ddb-sync` after bridge deploy to populate `dynamic_sheet` from D&D Beyond. Player-edited `hp_current` is preserved on re-sync.

## Sections vs description HTML sheet

| Section | `dynamic_sheet` keys |
|---------|----------------------|
| Header | `class_summary`, `prof_bonus`, `player_campaign`, `avatar_url` |
| Defenses | `ac`, `hp_current` (editable), `hp_max`, `speed`, `initiative`, `hit_dice` |
| Abilities | `str` … `cha` |
| Saving throws | `str_save` … `cha_save` |
| Skills & senses | `skills`, `passive_perception`, `passive_investigation`, `passive_insight` |
| Combat | `actions`, `bonus_actions`, `reactions` |
| Proficiencies | `proficiencies`, `languages`, `tools` |
| Spellcasting | `spellcasting_ability`, `spell_save_dc`, `spell_attack`, `spell_slots`, `spells_json` (collapsible cards; includes cantrips + ritual-only spells) |
| Sync | `ddb_last_sync` |

**Not on player sheet:** `features_traits`, `limited_use`, `equipment`, race/background/alignment/inspiration (same trim as description HTML).

## Spell cards

`spells_json` is a JSON array synced from D&D Beyond. Each entry: `name`, `level`, `level_label`, `school`, `concentration`, `ritual`, `body`.

Included spells: all cantrips; prepared / always-prepared; ritual spells even when not prepared.

DST JS renders collapsed `<details>` rows. Tags on the summary row: **Concentration**, **school** (Great House crest icon), **Ritual**, level label.

School → house crest mapping (campaign `/images/` paths):

| School | House | Image |
|--------|-------|-------|
| Abjuration | Meness | `/images/1546939/Meness.png` |
| Conjuration | Beltus | `/images/1546934/Beltus.png` |
| Divination | Goela | `/images/1546931/Goela.png` |
| Enchantment | Mabon | `/images/1546937/Mabon.png` |
| Evocation | Oestra | `/images/1546933/Oestra.png` |
| Illusion | Lithra | `/images/1546935/Lithra.png` |
| Necromancy | Samhain | `/images/1555017/Samhain.png` |
| Transmutation | Grimbolg | `/images/1546932/Grimbolg.png` |

`spells_prepared` remains in `dynamic_sheet` for the description HTML sheet; the DST uses `spells_json` only.

## Legal

Fan-created, unofficial. Not affiliated with Wizards of the Coast or D&D Beyond.
