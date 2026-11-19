import type {
  Character,
  CharacterGroup,
  CharacterVersion,
  UnassignedCharacter,
} from '../types';

const VERSION_TAGS = new Set(['alter_ego', 'familiar', 'npc', 'different_writer']);

/**
 * Normalizes nested versions from either modern `c.versions` or legacy/API `c.other_versions`.
 */
export function getCharacterVersionList(char: Character): CharacterVersion[] {
  if (char.versions && Array.isArray(char.versions) && char.versions.length > 0) {
    return char.versions;
  }
  if (char.other_versions && Array.isArray(char.other_versions)) {
    return char.other_versions;
  }
  return [];
}

/**
 * Extracts a nested version's type from `version_type` or `tags`.
 */
export function getCharacterVersionType(version: CharacterVersion): string | undefined {
  if (version.version_type) return version.version_type;
  return version.tags?.find(t => VERSION_TAGS.has(t));
}

/**
 * Returns all names (primary display name + aliases) for a character or version.
 */
export function getAllCharacterNames(
  char: Pick<Character | CharacterVersion | UnassignedCharacter, 'name' | 'names'>
): string[] {
  if (char.names && char.names.length > 0) {
    const cleaned = char.names.map(n => n.trim()).filter(Boolean);
    if (cleaned.length > 0) return cleaned;
  }
  if (char.name && char.name.trim()) {
    return [char.name.trim()];
  }
  return [];
}

/**
 * Returns the primary display name for a character, version, or unassigned character.
 */
export function getCharacterDisplayName(
  char: Pick<Character | CharacterVersion | UnassignedCharacter, 'name' | 'names'> & { id?: number }
): string {
  const names = getAllCharacterNames(char);
  if (names.length > 0) return names[0];
  return char.id != null ? `Character #${char.id}` : 'Unknown';
}

/**
 * Returns secondary aliases for a character (excluding the primary display name).
 */
export function getCharacterAliases(char: Character | UnassignedCharacter): string[] {
  const names = getAllCharacterNames(char);
  return names.length > 1 ? names.slice(1) : [];
}

/**
 * Returns the primary writer display string for a character or version.
 */
export function getCharacterWriterName(
  char: Pick<Character | CharacterVersion, 'writer' | 'writer_name'>,
  fallback?: string | null
): string | null {
  if (char.writer_name && char.writer_name.trim()) return char.writer_name.trim();
  if (char.writer && char.writer.length > 0 && char.writer[0]?.trim()) {
    return char.writer[0].trim();
  }
  return fallback || null;
}

/**
 * Returns the primary display name for a character group.
 */
export function getGroupDisplayName(group: CharacterGroup): string {
  if (group.names && group.names.length > 0 && group.names[0]?.trim()) {
    return group.names[0].trim();
  }
  if (group.name && group.name.trim()) return group.name.trim();
  return `Group #${group.id}`;
}

/**
 * Extracts member character IDs from a CharacterGroup regardless of whether members are IDs or objects.
 */
export function getGroupMemberIds(group: CharacterGroup): number[] {
  return (group.members || []).map(m => (typeof m === 'object' ? m.id : m));
}

/**
 * Resolves a character name by their ID from a list of characters.
 * Checks top-level characters AND nested versions in both `c.versions` and `c.other_versions`.
 */
export function resolveCharacterName(id: number, allCharacters: Character[]): string | null {
  for (const c of allCharacters) {
    if (c.id === id) {
      const names = getAllCharacterNames(c);
      if (names.length > 0) return names[0];
    }

    for (const v of getCharacterVersionList(c)) {
      if (v.id === id) {
        const names = getAllCharacterNames(v);
        if (names.length > 0) return names[0];
      }
    }
  }

  return null;
}

export interface CharacterPickerOption {
  key: string;
  kind: 'character' | 'group';
  id: number;
  displayName: string;
  searchNames: string[];
  writerName?: string | null;
  writerSearchNames: string[];
  isVersion?: boolean;
  versionType?: string;
  parentName?: string;
  memberCount?: number;
}

export interface BuildCharacterPickerOptionsConfig {
  includeVersions?: boolean;
  groups?: CharacterGroup[];
  excludeIds?: number[];
  fallbackOptions?: Array<{ id: number; name: string; writerName?: string | null }>;
}

/**
 * Builds searchable picker options for characters, optional nested versions, and optional groups.
 * Preserves all aliases in `searchNames` while keeping `displayName` as the primary name.
 */
export function buildCharacterPickerOptions(
  characters: Character[],
  config: BuildCharacterPickerOptionsConfig = {}
): CharacterPickerOption[] {
  const {
    includeVersions = false,
    groups = [],
    excludeIds = [],
    fallbackOptions = [],
  } = config;

  const excluded = new Set(excludeIds);
  const options: CharacterPickerOption[] = [];
  const seenCharIds = new Set<number>();

  for (const g of groups) {
    const gName = getGroupDisplayName(g);
    const gNames = (g.names || []).map(n => n.trim()).filter(Boolean);
    options.push({
      key: `group-${g.id}`,
      kind: 'group',
      id: g.id,
      displayName: gName,
      searchNames: gNames.length > 0 ? gNames : [gName],
      writerSearchNames: [],
      memberCount: getGroupMemberIds(g).length,
    });
  }

  for (const c of characters) {
    const charName = getCharacterDisplayName(c);
    const charNames = getAllCharacterNames(c);
    const writer = getCharacterWriterName(c);
    const writerNames = (c.writer || (writer ? [writer] : [])).map(w => w.trim()).filter(Boolean);

    if (!excluded.has(c.id) && !seenCharIds.has(c.id)) {
      seenCharIds.add(c.id);
      options.push({
        key: `char-${c.id}`,
        kind: 'character',
        id: c.id,
        displayName: charName,
        searchNames: charNames.length > 0 ? charNames : [charName],
        writerName: writer,
        writerSearchNames: writerNames,
      });
    }

    if (includeVersions) {
      for (const v of getCharacterVersionList(c)) {
        if (excluded.has(v.id) || seenCharIds.has(v.id)) continue;
        seenCharIds.add(v.id);
        const vName = getCharacterDisplayName(v);
        const vNames = getAllCharacterNames(v);
        const vWriter = getCharacterWriterName(v, writer);
        const vWriterNames = (v.writer && v.writer.length > 0 ? v.writer : writerNames)
          .map(w => w.trim())
          .filter(Boolean);

        options.push({
          key: `char-${v.id}`,
          kind: 'character',
          id: v.id,
          displayName: vName,
          searchNames: vNames.length > 0 ? vNames : [vName],
          writerName: vWriter,
          writerSearchNames: vWriterNames,
          isVersion: true,
          versionType: getCharacterVersionType(v),
          parentName: charName,
        });
      }
    }
  }

  for (const fb of fallbackOptions) {
    if (!excluded.has(fb.id) && !seenCharIds.has(fb.id)) {
      seenCharIds.add(fb.id);
      options.push({
        key: `char-${fb.id}`,
        kind: 'character',
        id: fb.id,
        displayName: fb.name,
        searchNames: [fb.name],
        writerName: fb.writerName ?? null,
        writerSearchNames: fb.writerName ? [fb.writerName] : [],
      });
    }
  }

  return options;
}

/**
 * Filters picker options by matching against primary names, aliases, IDs, writer names, or parent names.
 */
export function filterCharacterPickerOptions(
  options: CharacterPickerOption[],
  query: string
): CharacterPickerOption[] {
  const q = query.trim().toLowerCase();
  if (!q) return options;

  return options.filter(
    opt =>
      opt.searchNames.some(n => n.toLowerCase().includes(q)) ||
      String(opt.id).includes(q) ||
      opt.writerSearchNames.some(w => w.toLowerCase().includes(q)) ||
      (opt.parentName && opt.parentName.toLowerCase().includes(q))
  );
}
