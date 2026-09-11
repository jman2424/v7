import { error } from '@sveltejs/kit';
const sections = ['pipeline','test','implementation','usage','conversations','agent','website','integrations','catalog','offers','faqs','delivery','profile','branches','team','companies','errors'];
export function entries() { return sections.map(section => ({section})); }
export function load({ params }: { params: { section: string } }) {
  if (!sections.includes(params.section)) error(404, 'Page not found');
  return {};
}
