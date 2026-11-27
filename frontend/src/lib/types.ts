import type { CompanyForm, EntityType, Regime } from './company'

export type Role = 'admin' | 'accountant' | 'assistant' | 'client'

export interface User {
  id: number
  first_name: string
  last_name: string
  username: string
  role: Role
  is_active: boolean
}

export interface Invite {
  id: number
  kind: string
  link: string
  created_at: string
  expires_at: string
}

export interface ProxyForm {
  enabled: boolean
  host: string
  port: number
  username: string
  password: string
  rdns: boolean
}

export interface AppSettings {
  company: {
    name: string
    support_contact: string
    timezone: string
    privacy_policy_url: string
  }
  telegram: {
    bot_username: string
    mini_app_url: string
    login_widget?: boolean
    proxy: ProxyForm & { type: 'socks5'; has_password: boolean }
  }
  dadata: {
    enabled: boolean
    api_key: string
    secret_key: string
    has_api_key: boolean
    has_secret_key: boolean
    timeout_seconds: number
  }
  tasks: {
    show_notices_to_clients: boolean
  }
  notifications: {
    digest_time: string
    digest_workdays_only: boolean
    default_client_offsets_days: number[]
    remind_on_due_day: boolean
    fill_amount_workdays_before: number
    overdue_notify: boolean
    signature_offsets_days: number[]
    backup_alert: boolean
  }
}

export interface SettingsResponse {
  settings: AppSettings
  file_error: string | null
}

export interface CheckResult {
  ok: boolean
  message: string
}

export interface Backup {
  name: string
  created_at: string | null
  valid: boolean
}

export interface BotStatus {
  state:
    | 'unknown'
    | 'stopped'
    | 'problem'
    | 'connecting'
    | 'connected'
    | 'error'
    | 'unavailable'
  username?: string | null
  proxy?: string | null
  problem?: string | null
  last_error?: string | null
  last_success_at?: number | null
}

export interface Patent {
  id: number
  number: string
  region: string
  date_start: string
  date_end: string
  cost_kopecks: number | null
}

export interface Member {
  user_id: number
  first_name: string
  last_name: string
  username: string
  is_primary: boolean
  can_mark_paid: boolean
  receive_reminders: boolean
  bot_blocked: boolean
}

export interface Company extends CompanyForm {
  id: number
  is_archived: boolean
  accountant_id: number | null
  accountant_name: string
  dadata_updated_at: string | null
  patents: Patent[]
  members: Member[]
}

export interface CompanyListItem {
  id: number
  inn: string
  name: string
  short_name: string
  entity_type: EntityType
  main_regime: Regime
  nds_payer: boolean
  has_employees: boolean
  is_archived: boolean
  accountant_id: number | null
  accountant_name: string
  patents_count: number
  members_count: number
  has_blocked_member: boolean
  has_missing_amount: boolean
}

export interface Party {
  inn: string
  kpp: string
  ogrn: string
  name: string
  short_name: string
  address: string
  okved: string
  director_name: string
  entity_type: EntityType
  region_code: string
  status: string
}

export interface StaffMember {
  id: number
  name: string
}
