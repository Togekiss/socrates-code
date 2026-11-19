import { useEffect, useState } from 'react';
import { api } from '../api';
import type { Character, CharacterGroup, WriterDetailed } from '../types';

/**
 * Loads characters, character groups, and writers for a ready backup so Archive views
 * share a single roster-loading pattern.
 */
export function useArchiveRoster(backupId: string, isReady: boolean) {
  const [allCharacters, setAllCharacters] = useState<Character[]>([]);
  const [allGroups, setAllGroups] = useState<CharacterGroup[]>([]);
  const [allWriters, setAllWriters] = useState<WriterDetailed[]>([]);

  useEffect(() => {
    setAllCharacters([]);
    setAllGroups([]);
    setAllWriters([]);
  }, [backupId]);

  useEffect(() => {
    if (!backupId || !isReady) return;
    let cancelled = false;

    Promise.all([
      api.getCharacters(backupId).catch(() => [] as Character[]),
      api.getGroups(backupId).catch(() => [] as CharacterGroup[]),
      api.getWritersDetailed(backupId).catch(() => [] as WriterDetailed[]),
    ]).then(([charsRes, groupsRes, writersRes]) => {
      if (cancelled) return;
      setAllCharacters(Array.isArray(charsRes) ? charsRes : []);
      setAllGroups(Array.isArray(groupsRes) ? groupsRes : []);
      setAllWriters(Array.isArray(writersRes) ? writersRes : []);
    });

    return () => {
      cancelled = true;
    };
  }, [backupId, isReady]);

  return { allCharacters, allGroups, allWriters };
}
