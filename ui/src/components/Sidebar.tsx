import { Sidebar } from './layout/Sidebar';

export type TabType =
  | 'status'
  | 'run'
  | 'writers'
  | 'characters'
  | 'scenes'
  | 'chat_sessions'
  | 'events'
  | 'scene_issues'
  | 'flagged_messages'
  | 'admin'
  | 'new_backup';

export { Sidebar, type SidebarProps } from './layout/Sidebar';
export default Sidebar;
