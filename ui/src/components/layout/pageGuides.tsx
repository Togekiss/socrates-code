import React from 'react';
import { Badge } from '../ui';

export interface PageGuideEntry {
  title: string;
  content: React.ReactNode;
}

export const PAGE_GUIDES = {
  characters: {
    title: 'How Characters & Groups Work',
    content: (
      <>
        <p>
          Characters are automatically indexed from Discord dialogue and Tupperbox/webhook messages.
          Use this page to curate character names, tags, alternate versions, and writer ownership.
        </p>
        <div className="info-modal-list">
          <div className="info-modal-item">
            <Badge variant="accent" className="info-modal-badge">
              GROUPS
            </Badge>
            <span className="info-modal-text">
              Bundle related characters into a Character Group so they appear together here and can
              be filtered as a unit across Scenes, Chat Sessions, and Events.
            </span>
          </div>
          <div className="info-modal-item">
            <Badge variant="info" className="info-modal-badge">
              VERSIONS
            </Badge>
            <span className="info-modal-text">
              Nest duplicate or secondary forms under a primary character as{' '}
              <strong>Alter Ego</strong>, <strong>Familiar</strong>, or <strong>NPC</strong>, or
              merge true duplicates together.
            </span>
          </div>
          <div className="info-modal-item">
            <Badge variant="warning" className="info-modal-badge">
              WRITERS
            </Badge>
            <span className="info-modal-text">
              Assign characters to Writer profiles so <strong>★ By Me</strong> and writer filters
              stay accurate. Participants can edit and tag their own linked characters; Curators can
              manage the full roster.
            </span>
          </div>
        </div>
      </>
    ),
  },
  writers: {
    title: 'How Writers Work',
    content: (
      <>
        <p>
          Writer profiles represent the real players behind characters in this backup. Linking a
          writer to their Discord User ID powers personal filters across the workspace.
        </p>
        <div className="info-modal-list">
          <div className="info-modal-item">
            <Badge variant="accent" className="info-modal-badge">
              DISCORD LINK
            </Badge>
            <span className="info-modal-text">
              Attach a Discord snowflake ID so <strong>★ By Me</strong> automatically identifies that
              user&apos;s characters across Characters, Scenes, Chat Sessions, and Events.
            </span>
          </div>
          <div className="info-modal-item">
            <Badge variant="info" className="info-modal-badge">
              SUGGESTIONS
            </Badge>
            <span className="info-modal-text">
              Curators see automatic <strong>Discord Link Suggestions</strong> inferred from message
              authorship when an unlinked writer matches a Discord account.
            </span>
          </div>
          <div className="info-modal-item">
            <Badge variant="neutral" className="info-modal-badge">
              PRIVACY
            </Badge>
            <span className="info-modal-text">
              Discord User IDs for other writers are hidden for Viewers and Participants;
              Participants can edit their own linked profile.
            </span>
          </div>
        </div>
      </>
    ),
  },
  scenes: {
    title: 'How Scenes Work',
    content: (
      <>
        <p>
          Scenes represent contiguous roleplay arcs extracted from standard RP channels and
          threads. Use the filters to narrow down by characters, character groups, writers, status,
          channel type, or date range.
        </p>
        <div className="info-modal-list">
          <div className="info-modal-item">
            <Badge variant="neutral" className="info-modal-badge">
              SEARCH
            </Badge>
            <span className="info-modal-text">
              The Search input matches custom scene names, scene keys, channel names, and
              categories.
            </span>
          </div>
          <div className="info-modal-item">
            <Badge variant="accent" className="info-modal-badge">
              CHARACTERS
            </Badge>
            <span className="info-modal-text">
              Click any character chip inside a scene card to toggle it in your active filter.
              Switch between <strong>AND</strong> / <strong>OR</strong> logic and optionally include
              Alter Egos, Familiars, or NPCs in OR mode.
            </span>
          </div>
          <div className="info-modal-item">
            <Badge variant="danger" className="info-modal-badge">
              SPLIT (ISSUES)
            </Badge>
            <span className="info-modal-text">
              Scenes marked with issues or <code>Split (Issues)</code> had ambiguous boundaries
              during parsing and can be reviewed in the Scene Issues tab. Curators can edit custom
              names or merge adjacent scenes from a card&apos;s Edit button.
            </span>
          </div>
        </div>
      </>
    ),
  },
  chatSessions: {
    title: 'How Chat Sessions Work',
    content: (
      <>
        <p>
          Chat Sessions group continuous dialogue inside chatroom-style channels using activity
          clustering and participant continuity.
        </p>
        <div className="info-modal-list">
          <div className="info-modal-item">
            <Badge variant="neutral" className="info-modal-badge">
              SEARCH
            </Badge>
            <span className="info-modal-text">
              The Search input matches custom session names, session keys, channel names, and
              categories.
            </span>
          </div>
          <div className="info-modal-item">
            <Badge variant="accent" className="info-modal-badge">
              PARTICIPANTS
            </Badge>
            <span className="info-modal-text">
              Each session shows its duration badge and participating characters in order of
              appearance. Click any character chip to filter by that character.
            </span>
          </div>
          <div className="info-modal-item">
            <Badge variant="warning" className="info-modal-badge">
              CURATION
            </Badge>
            <span className="info-modal-text">
              Curators can assign custom session names or merge adjacent sessions from the Edit
              button, and resolve boundary flags in Scene Issues.
            </span>
          </div>
        </div>
      </>
    ),
  },
  events: {
    title: 'How Events Work',
    content: (
      <>
        <p>
          Events cluster contemporary roleplay across multiple location channels and threads into
          unified story timelines.
        </p>
        <div className="info-modal-list">
          <div className="info-modal-item">
            <Badge variant="neutral" className="info-modal-badge">
              SEARCH
            </Badge>
            <span className="info-modal-text">
              The Search input matches event names, event keys, location custom names, channel
              names, and categories.
            </span>
          </div>
          <div className="info-modal-item">
            <Badge variant="accent" className="info-modal-badge">
              MOVEMENTS
            </Badge>
            <span className="info-modal-text">
              Expand channels or select a participating character inside an event card to inspect
              arrival/departure times and cross-channel movement hops.
            </span>
          </div>
          <div className="info-modal-item">
            <Badge variant="warning" className="info-modal-badge">
              CURATION
            </Badge>
            <span className="info-modal-text">
              Curators can rename events, merge contiguous events, or split an event into two parts
              from the card&apos;s Edit modal.
            </span>
          </div>
        </div>
      </>
    ),
  },
  sceneIssues: {
    title: 'How "Scene Issues" Work',
    content: (
      <>
        <p>
          Socrates detects scenes using pattern recognition. When{' '}
          <code className="text-accent">[END]</code> tags aren&apos;t clear, it makes a decision and
          leaves it here for human review.
        </p>
        <div className="info-modal-list">
          <div className="info-modal-item">
            <Badge variant="warning" className="info-modal-badge">
              AUTO SPLIT
            </Badge>
            <span className="info-modal-text">
              Socrates registered this as the start of a new scene. If this is a mistake, you can
              merge the two scenes.
            </span>
          </div>
          <div className="info-modal-item">
            <Badge variant="accent" className="info-modal-badge">
              SOFT BOUNDARY
            </Badge>
            <span className="info-modal-text">
              Socrates doubted, but didn&apos;t start a new scene. If this is a mistake, you can
              register this as a new scene.
            </span>
          </div>
          <div className="info-modal-item">
            <Badge variant="neutral" className="info-modal-badge">
              MANUAL SPLIT
            </Badge>
            <span className="info-modal-text">
              Use <strong>Manual Split</strong> if a boundary was missed completely, or reopen a
              resolved issue to undo the previous merge/split.
            </span>
          </div>
        </div>
      </>
    ),
  },
  flaggedMessages: {
    title: 'How Flagged Messages Work',
    content: (
      <>
        <p>
          Flagged Messages are individual Discord messages that Socrates could not confidently
          classify during parsing, such as failed Tupperbox proxies or ambiguous OOC markers.
        </p>
        <div className="info-modal-list">
          <div className="info-modal-item">
            <Badge variant="accent" className="info-modal-badge">
              PROMOTE
            </Badge>
            <span className="info-modal-text">
              Assign a flagged message to an existing or new character without altering raw Discord
              backups on disk.
            </span>
          </div>
          <div className="info-modal-item">
            <Badge variant="success" className="info-modal-badge">
              KEEP
            </Badge>
            <span className="info-modal-text">
              Confirm the message belongs in the scene/session as-is (for example, valid narration
              or dialogue).
            </span>
          </div>
          <div className="info-modal-item">
            <Badge variant="neutral" className="info-modal-badge">
              IGNORE
            </Badge>
            <span className="info-modal-text">
              Mark out-of-character chatter or bot noise so it is excluded from roleplay parsing. Use{' '}
              <strong>Add Message</strong> to manually flag any message by link or ID.
            </span>
          </div>
        </div>
      </>
    ),
  },
} as const satisfies Record<string, PageGuideEntry>;

export type PageGuideKey = keyof typeof PAGE_GUIDES;
