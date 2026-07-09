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
  spells.forEach(function (spell) {
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
    if (spell.level_label) {
      tags.appendChild(_spellTag(spell.level_label, "ddb-tag-level"));
    }
    summary.appendChild(tags);

    details.appendChild(summary);

    var body = document.createElement("div");
    body.className = "ddb-spell-body ddb-pre";
    body.textContent = spell.body || "";
    details.appendChild(body);

    mount.appendChild(details);
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
  var spellSlots = _fieldText(container, "dsf_spell_slots");
  var spellAbility = _fieldText(container, "dsf_spellcasting_ability");
  var spellSection = container.querySelector(".ddb-spellcasting");
  if (spellSection && !spellSlots && !hasSpellCards && !spellAbility) {
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

function sindrel_beyond_dataChange(options) {}

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
