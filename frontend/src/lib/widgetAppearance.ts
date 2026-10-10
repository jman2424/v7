export type Widget = {
  chat_title: string; assistant_name: string; greeting: string; avatar: string;
  company_logo_url: string; style: string; accent_color: string; allowed_origins: string[];
  background_color: string; surface_color: string; text_color: string; bubble_color: string;
};
export type ColourKey = 'accent_color' | 'background_color' | 'surface_color' | 'text_color' | 'bubble_color';
export type PreviewTheme = Partial<Record<'primary_color' | 'secondary_color' | 'text_color' | 'accent_color' | 'font_family', string>>;
export type AppearancePreset = { name: string; description: string; settings: Pick<Widget, 'style' | ColourKey> };

export const appearancePresets: AppearancePreset[] = [
  { name:'Website demo', description:'Studio layout with green accents and soft grey surfaces, as seen on our website.',
    settings:{ style:'studio', accent_color:'#086849', background_color:'#FFFFFF', surface_color:'#F2F4F3', text_color:'#27332F', bubble_color:'#E8F3EC' } }
];
export function applyAppearancePreset(widget: Widget, preset: AppearancePreset): Widget {
  return { ...widget, ...preset.settings };
}
export function appearancePresetMatches(widget: Widget, preset: AppearancePreset): boolean {
  const fields: ('style' | ColourKey)[] = ['style', 'accent_color', 'background_color', 'surface_color', 'text_color', 'bubble_color'];
  return fields.every(key => widget[key].toLowerCase() === preset.settings[key].toLowerCase());
}

type Palette = { background: string; surface: string; field: string; text: string; muted: string; bubble: string; border: string };
export const widgetStyles = [
  { id: 'midnight', name: 'Midnight', description: 'Focused dark chat', radius: 16, palette: { background:'#0e1016', surface:'#131826', field:'#191e2a', text:'#eaf0ff', muted:'#aeb9d0', bubble:'#0b1c12', border:'#343b4d' } },
  { id: 'daylight', name: 'Daylight', description: 'Familiar and bright', radius: 12, palette: { background:'#f3f6fa', surface:'#ffffff', field:'#f7f9fc', text:'#182338', muted:'#48576e', bubble:'#e8f3ee', border:'#c9d2de' } },
  { id: 'minimal', name: 'Minimal', description: 'Simple, open layout', radius: 2, palette: { background:'#ffffff', surface:'#ffffff', field:'#f7f9f7', text:'#202422', muted:'#505a53', bubble:'#f1f6f2', border:'#d8dfda' } },
  { id: 'editorial', name: 'Editorial', description: 'Classic serif detail', radius: 0, palette: { background:'#f5f0e6', surface:'#fffaf0', field:'#fffdf7', text:'#2b281f', muted:'#60594e', bubble:'#eee8d8', border:'#a89f8f' } },
  { id: 'neon', name: 'Neon', description: 'Vivid, technical feel', radius: 6, palette: { background:'#080c16', surface:'#101729', field:'#0d1628', text:'#eff8ff', muted:'#b8cbe5', bubble:'#142a32', border:'#50617d' } },
  { id: 'warm', name: 'Warm', description: 'Welcoming and rounded', radius: 28, palette: { background:'#f7eee6', surface:'#fff8f1', field:'#fffaf5', text:'#3e2d2b', muted:'#705b55', bubble:'#f4e3d9', border:'#d4bdb0' } },
  { id: 'glass', name: 'Glass', description: 'Layered colour', radius: 24, palette: { background:'#19365d', surface:'#243f63', field:'#2c496f', text:'#ffffff', muted:'#e1ecf8', bubble:'#35577a', border:'#889dbb' } },
  { id: 'studio', name: 'Studio', description: 'Structured business chat', radius: 12, palette: { background:'#f4f5f7', surface:'#ffffff', field:'#f7f8fa', text:'#202933', muted:'#576371', bubble:'#e8edf4', border:'#cbd3dc' } },
  { id: 'soft', name: 'Soft', description: 'Calm, gentle shapes', radius: 24, palette: { background:'#eef5f1', surface:'#fbfdfb', field:'#f1f7f2', text:'#233d30', muted:'#526c5c', bubble:'#dcefe3', border:'#becfc3' } },
  { id: 'bold', name: 'Bold', description: 'A strong brand header', radius: 10, palette: { background:'#f4f5f5', surface:'#ffffff', field:'#eef1f0', text:'#142b23', muted:'#52665d', bubble:'#e4f4eb', border:'#bac9c1' } }
];
export const brandPalettes = [
  { name:'Forest', accent_color:'#087F5B', background_color:'#F1F6F3', surface_color:'#FFFFFF', text_color:'#193A2A', bubble_color:'#D5EADF' },
  { name:'Ocean', accent_color:'#155E75', background_color:'#F0F5F8', surface_color:'#FFFFFF', text_color:'#183744', bubble_color:'#CDE8EF' },
  { name:'Plum', accent_color:'#7E3F70', background_color:'#F7F2F7', surface_color:'#FFFFFF', text_color:'#382C3A', bubble_color:'#EDD8E8' },
  { name:'Terracotta', accent_color:'#A44830', background_color:'#FAF3EE', surface_color:'#FFFDFA', text_color:'#432C24', bubble_color:'#F2D8C8' },
  { name:'Gold', accent_color:'#946600', background_color:'#F8F5EC', surface_color:'#FFFFFF', text_color:'#3F3520', bubble_color:'#F2E5BC' },
  { name:'Monochrome', accent_color:'#262626', background_color:'#F4F4F4', surface_color:'#FFFFFF', text_color:'#202020', bubble_color:'#E4E4E4' }
];
export const isHexColour = (value: string) => /^#[0-9a-f]{6}$/i.test(value);
function luminance(hex: string) {
  const rgb = [1,3,5].map(index => parseInt(hex.slice(index,index+2),16) / 255).map(value => value <= .04045 ? value / 12.92 : ((value + .055) / 1.055) ** 2.4);
  return rgb[0] * .2126 + rgb[1] * .7152 + rgb[2] * .0722;
}
function contrast(background: string, preferred: string) {
  const bg = luminance(background), text = luminance(preferred);
  return (Math.max(bg,text) + .05) / (Math.min(bg,text) + .05);
}
function automaticText(background: string) {
  const bg = luminance(background);
  return (bg + .05) / .05 >= 1.05 / (bg + .05) ? '#000000' : '#FFFFFF';
}
export function readableText(background: string, preferred = '#172B26') {
  return contrast(background,preferred) >= 4.5 ? preferred : automaticText(background);
}
function mix(first: string, second: string, amount: number) {
  return '#'+[1,3,5].map(index => Math.round(parseInt(first.slice(index,index+2),16)*(1-amount)+parseInt(second.slice(index,index+2),16)*amount).toString(16).padStart(2,'0')).join('');
}
export function widgetTheme(widget: Widget, legacy: PreviewTheme = {}) {
  const style = widgetStyles.find(option => option.id === widget.style) || widgetStyles[0];
  const palette: Palette = style.palette;
  const pick = (key: ColourKey, fallback: string) => isHexColour(widget[key]) ? widget[key] : fallback;
  const legacyColour = (key: keyof PreviewTheme) => isHexColour(legacy[key] || '') ? legacy[key]! : '';
  const accent = pick('accent_color',legacyColour('accent_color') || legacyColour('primary_color') || '#274060');
  const customBackground = pick('background_color',style.id === 'midnight' ? legacyColour('secondary_color') : '');
  const background = customBackground || palette.background, customSurface = pick('surface_color','');
  const surface = customSurface || (customBackground ? mix(background,luminance(background) > .45 ? '#000000' : '#FFFFFF',.04) : palette.surface);
  const field = customSurface || customBackground ? mix(surface,automaticText(surface),.04) : palette.field;
  const text = pick('text_color',(style.id === 'midnight' ? legacyColour('text_color') : '') || palette.text);
  const bubble = pick('bubble_color',customBackground ? mix(background,accent,.16) : palette.bubble);
  const panelText = readableText(surface,text);
  const muted = readableText(surface,mix(panelText,surface,.18));
  const font = legacy.font_family || '';
  const launcherSurfaces: Record<string,string> = {daylight:'#FFFFFF',minimal:'#FFFFFF',editorial:'#F8F2E8',neon:'#101322',warm:'#493228',glass:'#182634',studio:'#FFFFFF',soft:'#F1F8F5'};
  const launcherTexts: Record<string,string> = {daylight:'#172033',minimal:'#172033',editorial:'#302B26',neon:accent,warm:'#FFFFFF',glass:'#FFFFFF',studio:'#172B26',soft:'#172B26'};
  const launcherBackground = customSurface || launcherSurfaces[style.id] || accent;
  const launcherText = readableText(launcherBackground,pick('text_color',launcherTexts[style.id] || readableText(accent,'#102019')));
  const launcherRadius: Record<string,number> = {midnight:16,daylight:12,minimal:3,editorial:2,neon:16,warm:28,glass:18,studio:12,soft:24,bold:10};
  const defaultFont = style.id === 'editorial' ? 'Georgia, "Times New Roman", serif' : style.id === 'neon' ? 'ui-monospace, SFMono-Regular, Consolas, monospace' : 'ui-sans-serif, system-ui, -apple-system, Inter, Roboto, "Helvetica Neue", Arial';
  return { style, accent, background, surface, field, text, bubble, border:mix(surface,automaticText(surface),.5),
    backgroundText:readableText(background,text),
    panelText:readableText(surface,text), fieldText:readableText(field,text), bubbleText:readableText(bubble,text),
    accentText:automaticText(accent), muted,
    launcherBackground,launcherText,launcherRadius:launcherRadius[style.id],
    fontFamily:font.length <= 120 && /^[\w\s,.'"\-]+$/.test(font) ? font : defaultFont };
}
