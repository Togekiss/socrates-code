import type { Character, UnassignedCharacter } from '../types';

/**
 * Resolves a character name by their ID from a list of characters.
 * Checks top-level characters (names[0] || name) AND nested versions
 * in both `c.versions` (v.name) and legacy `c.other_versions` (v.names[0] || v.name).
 * Permanently eliminates the `versions` vs `other_versions` divergence bug.
 */
export function resolveCharacterName(id: number, allCharacters: Character[]): string | null {
  for (const c of allCharacters) {
    if (c.id === id) {
      if (c.names && c.names.length > 0 && c.names[0]) {
        return c.names[0];
      }
      if (c.name) {
        return c.name;
      }
    }

    // Check nested versions in modern c.versions
    if (c.versions && Array.isArray(c.versions)) {
      const match = c.versions.find(v => v.id === id);
      if (match && match.name) {
        return match.name;
      }
    }

    // Check nested versions in legacy c.other_versions
    const legacy = c.other_versions;
    if (legacy && Array.isArray(legacy)) {
      const match = legacy.find(v => v.id === id);
      if (match) {
        if (match.names && match.names.length > 0 && match.names[0]) {
          return match.names[0];
        }
        if (match.name) {
          return match.name;
        }
      }
    }
  }

  return null;
}

/**
 * Returns the primary display name for a character or unassigned character.
 */
export function getCharacterDisplayName(char: Character | UnassignedCharacter): string {
  if (char.names && char.names.length > 0 && char.names[0]) {
    return char.names[0];
  }
  return char.name || 'Unknown';
}

/**
 * Returns secondary aliases for a character (excluding the primary display name).
 */
export function getCharacterAliases(char: Character | UnassignedCharacter): string[] {
  if (char.names && char.names.length > 1) {
    return char.names.slice(1);
  }
  return [];
}
