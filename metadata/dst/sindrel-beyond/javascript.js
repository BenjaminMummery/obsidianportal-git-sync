// Display hooks for Obsidian Portal DST (slug: sindrel_beyond / sinbdrel_beyond).

// Great House crests on The Lords of Sindrel campaign (school → house symbol).
var SINDREL_SCHOOL_ICONS = {
  abjuration: "/images/1546939/Meness.png",
  conjuration: "/images/1546934/Beltus.png",
  divination: "/images/1546931/Goela.png",
  enchantment: "/images/1546937/Mabon.png",
  evocation: "/images/1546933/Oestra.png",
  illusion: "/images/1546935/Lithra.png",
  necromancy: "/images/1555017/Samhain.png",
  transmutation: "/images/1546932/Grimbolg.png",
};

function _sindrelBeyondContainer(options) {
  return options.containerId ? document.getElementById(options.containerId) : null;
}

function _fieldText(container, className) {
  var el = container.querySelector("." + className);
  if (!el) {
    return "";
  }
  return (el.textContent || "").trim();
}

function _hideIfEmpty(container, fieldClass, bucketSelector) {
  var text = _fieldText(container, fieldClass);
  var bucket = container.querySelector(bucketSelector);
  if (bucket && !text) {
    bucket.style.display = "none";
  }
}

function _formatCombatField(container, fieldClass) {
  var el = container.querySelector("." + fieldClass);
  if (!el) {
    return;
  }
  var text = (el.textContent || "").trim();
  if (!text) {
    return;
  }
  el.innerHTML = text
    .split("\n")
    .map(function (line) {
      var match = line.match(/^([^.]+)\.\s*(.*)$/);
      if (!match) {
        return line;
      }
      return "<strong>" + match[1] + ".</strong> " + match[2];
    })
    .join("<br>\n");
}

function _spellLevelHeading(level) {
  if (level === 0) {
    return "Cantrips";
  }
  var suffix = "th";
  if (level % 100 < 11 || level % 100 > 20) {
    suffix = { 1: "st", 2: "nd", 3: "rd" }[level % 10] || "th";
  }
  return level + suffix + " Level";
}

function _spellSlotsUsedMap(container) {
  var raw = _fieldText(container, "dsf_spell_slots_used_json");
  if (!raw) {
    return {};
  }
  try {
    return JSON.parse(raw);
  } catch (e) {
    return {};
  }
}

function _writeSpellSlotsUsedMap(container, usedMap) {
  var field = container.querySelector(".dsf_spell_slots_used_json");
  if (field) {
    field.textContent = JSON.stringify(usedMap);
  }
}

function _sheetEditable(container) {
  var root = container.closest(".ds_sindrel_beyond, .ds_sinbdrel_beyond");
  return !!(root && root.classList.contains("editable"));
}

function _slotUsedCount(slot, usedMap) {
  var key = String(slot.level);
  if (Object.prototype.hasOwnProperty.call(usedMap, key)) {
    return Math.max(0, Math.min(parseInt(usedMap[key], 10) || 0, slot.max || 0));
  }
  if (slot.used != null) {
    return Math.max(0, Math.min(parseInt(slot.used, 10) || 0, slot.max || 0));
  }
  return 0;
}

function _renderSpellSlots(container) {
  var mount = container.querySelector(".ddb-spell-slots");
  var raw = _fieldText(container, "dsf_spell_slots_json");
  if (!mount || !raw || raw === "[]") {
    return false;
  }

  var slots;
  try {
    slots = JSON.parse(raw);
  } catch (e) {
    return false;
  }
  if (!Array.isArray(slots) || !slots.length) {
    return false;
  }

  var usedMap = _spellSlotsUsedMap(container);
  var editable = _sheetEditable(container);
  mount.innerHTML = "";
  slots.forEach(function (slot) {
    var row = document.createElement("div");
    row.className = "ddb-spell-slot-row";

    var label = document.createElement("span");
    label.className = "ddb-spell-slot-label";
    label.textContent = slot.label || "";
    row.appendChild(label);

    var marks = document.createElement("span");
    marks.className = "ddb-spell-slot-marks";

    var max = slot.max || 0;
    var used = _slotUsedCount(slot, usedMap);
    for (var i = 0; i < max; i++) {
      var mark = document.createElement("span");
      mark.className =
        "ddb-slot-mark " + (i < used ? "ddb-slot-mark-used" : "ddb-slot-mark-open");
      mark.setAttribute("aria-hidden", "true");
      if (editable) {
        mark.className += " ddb-slot-mark-editable";
        (function (slotLevel, index, slotMax) {
          mark.addEventListener("click", function () {
            var currentMap = _spellSlotsUsedMap(container);
            var currentUsed = _slotUsedCount(slot, currentMap);
            var nextUsed = currentUsed;
            if (index < currentUsed) {
              nextUsed = index;
            } else if (index === currentUsed && currentUsed < slotMax) {
              nextUsed = currentUsed + 1;
            }
            currentMap[String(slotLevel)] = nextUsed;
            _writeSpellSlotsUsedMap(container, currentMap);
            _renderSpellSlots(container);
          });
        })(slot.level, i, max);
      }
      marks.appendChild(mark);
    }

    row.appendChild(marks);
    mount.appendChild(row);
  });
  return true;
}

function _spellMetaBlock(spell) {
  var meta = document.createElement("div");
  meta.className = "ddb-spell-meta";
  var rows = [
    ["Casting Time", spell.casting_time],
    ["Range", spell.range],
    ["Hit/DC", spell.hit_dc],
    ["Components", spell.components],
    ["Duration", spell.duration],
  ];
  rows.forEach(function (row) {
    var value = (row[1] || "").trim();
    if (!value || value === "—") {
      return;
    }
    var line = document.createElement("div");
    line.className = "ddb-spell-meta-row";
    var label = document.createElement("span");
    label.className = "ddb-spell-meta-label";
    label.textContent = row[0];
    var text = document.createElement("span");
    text.className = "ddb-spell-meta-value";
    text.textContent = value;
    line.appendChild(label);
    line.appendChild(text);
    meta.appendChild(line);
  });
  return meta;
}

function _spellTag(label, className) {
  var tag = document.createElement("span");
  tag.className = "ddb-tag " + className;
  tag.textContent = label;
  return tag;
}

function _schoolTag(spell) {
  var school = (spell.school || "").trim().toLowerCase();
  var tag = document.createElement("span");
  tag.className = "ddb-tag ddb-tag-school";
  tag.title = school ? school.charAt(0).toUpperCase() + school.slice(1) : "School";

  var iconSrc = SINDREL_SCHOOL_ICONS[school];
  if (iconSrc) {
    var img = document.createElement("img");
    img.className = "ddb-school-icon";
    img.alt = tag.title;
    img.src = iconSrc;
    img.addEventListener("error", function () {
      img.remove();
      if (!tag.textContent) {
        tag.textContent = tag.title;
      }
    });
    tag.appendChild(img);
  } else if (school) {
    tag.textContent = school.charAt(0).toUpperCase() + school.slice(1);
  }
  return tag;
}

function _profMark(proficient, expertise) {
  var mark = document.createElement("span");
  mark.className = "ddb-prof-mark";
  if (expertise) {
    mark.className += " ddb-prof-mark-expertise";
    mark.setAttribute("aria-label", "Expertise");
  } else if (proficient) {
    mark.className += " ddb-prof-mark-filled";
    mark.setAttribute("aria-label", "Proficient");
  } else {
    mark.className += " ddb-prof-mark-hollow";
    mark.setAttribute("aria-label", "Not proficient");
  }
  return mark;
}

function _checkRow(name, bonus, proficient, expertise) {
  var row = document.createElement("div");
  row.className = "ddb-check-row";

  row.appendChild(_profMark(proficient, expertise));

  var label = document.createElement("span");
  label.className = "ddb-check-name";
  label.textContent = name;
  row.appendChild(label);

  var value = document.createElement("span");
  value.className = "ddb-check-bonus";
  value.textContent = bonus;
  row.appendChild(value);

  return row;
}

function _renderAbilityBlocks(container) {
  var mount = container.querySelector(".ddb-ability-blocks");
  var raw = _fieldText(container, "dsf_ability_blocks_json");
  if (!mount || !raw || raw === "[]") {
    return false;
  }

  var blocks;
  try {
    blocks = JSON.parse(raw);
  } catch (e) {
    return false;
  }
  if (!Array.isArray(blocks) || !blocks.length) {
    return false;
  }

  mount.innerHTML = "";
  blocks.forEach(function (block) {
    var section = document.createElement("div");
    section.className = "ddb-ability-block";

    var header = document.createElement("div");
    header.className = "ddb-ability-header";

    var scoreBox = document.createElement("div");
    scoreBox.className = "ddb-score-box";

    var mod = document.createElement("span");
    mod.className = "ddb-score-mod";
    mod.textContent = block.modifier || "";
    scoreBox.appendChild(mod);

    var score = document.createElement("span");
    score.className = "ddb-score-value";
    score.textContent = block.score != null ? String(block.score) : "";
    scoreBox.appendChild(score);

    header.appendChild(scoreBox);

    var abilityLabel = document.createElement("span");
    abilityLabel.className = "ddb-ability-label";
    abilityLabel.textContent = block.label || "";
    header.appendChild(abilityLabel);

    section.appendChild(header);

    var checks = document.createElement("div");
    checks.className = "ddb-check-list";

    if (block.save) {
      checks.appendChild(
        _checkRow(
          "Saving Throw",
          block.save.bonus || "",
          !!block.save.proficient,
          false
        )
      );
    }

    (block.skills || []).forEach(function (skill) {
      checks.appendChild(
        _checkRow(
          skill.name || "",
          skill.bonus || "",
          !!skill.proficient,
          !!skill.expertise
        )
      );
    });

    section.appendChild(checks);
    mount.appendChild(section);
  });
  return true;
}

function _renderSpellCards(container) {
  var mount = container.querySelector(".ddb-spell-cards");
  var raw = _fieldText(container, "dsf_spells_json");
  if (!mount || !raw || raw === "[]") {
    return false;
  }

  var spells;
  try {
    spells = JSON.parse(raw);
  } catch (e) {
    return false;
  }
  if (!Array.isArray(spells) || !spells.length) {
    return false;
  }

  mount.innerHTML = "";
  var byLevel = {};
  spells.forEach(function (spell) {
    var level = spell.level != null ? spell.level : 0;
    if (!byLevel[level]) {
      byLevel[level] = [];
    }
    byLevel[level].push(spell);
  });

  Object.keys(byLevel)
    .map(Number)
    .sort(function (a, b) {
      return a - b;
    })
    .forEach(function (level) {
      var heading = document.createElement("h4");
      heading.className = "ddb-spell-level-title";
      heading.textContent = _spellLevelHeading(level);
      mount.appendChild(heading);

      byLevel[level].forEach(function (spell) {
        var details = document.createElement("details");
        details.className = "ddb-spell-card";

        var summary = document.createElement("summary");
        summary.className = "ddb-spell-summary";

        var name = document.createElement("span");
        name.className = "ddb-spell-name";
        name.textContent = spell.name || "Spell";
        summary.appendChild(name);

        var tags = document.createElement("span");
        tags.className = "ddb-spell-tags";
        if (spell.concentration) {
          tags.appendChild(_spellTag("Concentration", "ddb-tag-concentration"));
        }
        tags.appendChild(_schoolTag(spell));
        if (spell.ritual) {
          tags.appendChild(_spellTag("Ritual", "ddb-tag-ritual"));
        }
        summary.appendChild(tags);

        details.appendChild(summary);

        details.appendChild(_spellMetaBlock(spell));

        var body = document.createElement("div");
        body.className = "ddb-spell-body ddb-pre";
        body.textContent = spell.body || "";
        details.appendChild(body);

        mount.appendChild(details);
      });
    });
  return true;
}

function sindrel_beyond_dataPreLoad(options) {}

function sindrel_beyond_dataPostLoad(options) {
  var container = _sindrelBeyondContainer(options);
  if (!container) {
    return;
  }

  var avatarUrl = _fieldText(container, "dsf_avatar_url");
  var avatarWrap = container.querySelector(".ddb-avatar-wrap");
  var avatarField = container.querySelector(".dsf_avatar_url");
  if (avatarField && avatarUrl) {
    avatarField.innerHTML =
      '<img src="' + avatarUrl.replace(/"/g, "&quot;") + '" alt="">';
  } else if (avatarWrap) {
    avatarWrap.style.display = "none";
  }

  _renderAbilityBlocks(container);

  _formatCombatField(container, "dsf_actions");
  _formatCombatField(container, "dsf_bonus_actions");
  _formatCombatField(container, "dsf_reactions");

  _hideIfEmpty(container, "dsf_actions", '[data-bucket="actions"]');
  _hideIfEmpty(container, "dsf_bonus_actions", '[data-bucket="bonus_actions"]');
  _hideIfEmpty(container, "dsf_reactions", '[data-bucket="reactions"]');

  var combat = container.querySelector(".ddb-combat");
  if (combat) {
    var buckets = combat.querySelectorAll(".ddb-combat-bucket");
    var anyVisible = false;
    buckets.forEach(function (bucket) {
      if (bucket.style.display !== "none") {
        anyVisible = true;
      }
    });
    if (!anyVisible) {
      combat.style.display = "none";
    }
  }

  var hasSpellCards = _renderSpellCards(container);
  var hasSpellSlots = _renderSpellSlots(container);
  var spellAbility = _fieldText(container, "dsf_spellcasting_ability");
  var spellSection = container.querySelector(".ddb-spellcasting");
  if (spellSection && !hasSpellSlots && !hasSpellCards && !spellAbility) {
    spellSection.style.display = "none";
  }

  var sync = _fieldText(container, "dsf_ddb_last_sync");
  var syncRow = container.querySelector(".ddb-sync");
  if (syncRow && !sync) {
    syncRow.style.display = "none";
  }

  var limited = container.querySelector(".ddb-limited-use");
  if (limited && !_fieldText(container, "dsf_limited_use")) {
    limited.style.display = "none";
  }

  var status = container.querySelector(".ddb-status");
  if (status) {
    var hasConditions = !!_fieldText(container, "dsf_conditions");
    var hasDeathSaves = !!_fieldText(container, "dsf_death_saves");
    if (!hasConditions && !hasDeathSaves) {
      status.style.display = "none";
    }
  }
}

function sindrel_beyond_dataChange(options) {
  sindrel_beyond_dataPostLoad(options);
}

// OP slug typo on installed template.
function sinbdrel_beyond_dataPreLoad(options) {
  sindrel_beyond_dataPreLoad(options);
}
function sinbdrel_beyond_dataPostLoad(options) {
  sindrel_beyond_dataPostLoad(options);
}
function sinbdrel_beyond_dataChange(options) {
  sindrel_beyond_dataChange(options);
}
