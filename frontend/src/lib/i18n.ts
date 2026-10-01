import { derived, writable } from 'svelte/store';
import dictionary from '../../../dashboard/static/i18n/ui.json';
import featureDictionary from '../../../dashboard/static/i18n/features.json';

export const languages = [
  {id: 'en', name: 'English', dir: 'ltr'},
  {id: 'es', name: 'Español', dir: 'ltr'},
  {id: 'fr', name: 'Français', dir: 'ltr'},
  {id: 'ar', name: 'العربية', dir: 'rtl'}
] as const;
export type Language = typeof languages[number]['id'];
export const language = writable<Language>('en');
const messages: Record<string, Record<string, string>> = {};
for (const option of languages) {
  const key = option.id as keyof typeof dictionary;
  messages[key] = {...(dictionary[key] || {}), ...(featureDictionary[key] || {})};
}
export const t = derived(language, current => (text: string) => messages[current]?.[text] || text);

export function cookieValue(name: string): string {
  const value = document.cookie.split('; ').find(item => item.startsWith(name + '='));
  if (!value) return '';
  try { return decodeURIComponent(value.slice(name.length + 1)); }
  catch { return ''; }
}

export function preferenceChoice(): 'all' | 'essential' | '' {
  const value = cookieValue('v7_preferences');
  return value === 'all' || value === 'essential' ? value : '';
}

function preferenceCookie(name: string, value: string, maxAge: number) {
  document.cookie = `${name}=${encodeURIComponent(value)}; Path=/; Max-Age=${maxAge}; SameSite=Lax${location.protocol === 'https:' ? '; Secure' : ''}`;
}

export function setLanguage(value: string) {
  const selected = languages.find(item => item.id === value) || languages[0];
  language.set(selected.id);
  document.documentElement.lang = selected.id;
  document.documentElement.dir = selected.dir;
  if (preferenceChoice() === 'all') preferenceCookie('v7_language', selected.id, 180 * 86400);
}

export function initialiseLanguage() {
  const saved = preferenceChoice() === 'all' ? cookieValue('v7_language') : '';
  setLanguage(saved || navigator.language.split('-')[0]);
}

export function choosePreferences(value: 'all' | 'essential') {
  preferenceCookie('v7_preferences', value, 180 * 86400);
  if (value === 'essential') preferenceCookie('v7_language', '', 0);
  else setLanguage(document.documentElement.lang);
  window.dispatchEvent(new Event('v7-preferences-changed'));
}
