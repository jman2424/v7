import configuration from '../../../service/console_navigation.json';

export type WorkspaceView = {id:string;label:string;section:string;hidden?:boolean;parent?:string};
export type Workspace = {id:string;label:string;description:string;icon:string;views:WorkspaceView[]};
export type WorkspaceLocation = {workspace:string;view:string;panel?:string};
export const workspaces:Workspace[] = configuration.workspaces;
export const platformWorkspace:Workspace = configuration.platform;
export const workspaceDefinitions = [...workspaces,platformWorkspace];
export function workspaceAllowed(workspace:string,operator:boolean){
  return workspace==='platform'?operator:workspaces.some(item=>item.id===workspace);
}

export function legacyLocation(section:string):WorkspaceLocation {
  if(section==='platform')return {workspace:'platform',view:'overview'};
  const aliases=configuration.aliases as Record<string,WorkspaceLocation>;
  if(aliases[section])return {...aliases[section]};
  for(const workspace of workspaces){
    const view=workspace.views.find(item=>item.section===section);
    if(view)return {workspace:workspace.id,view:view.id};
  }
  if(section==='application')return {workspace:'home',view:'application'};
  return {workspace:'home',view:'overview'};
}

export function workspaceHref(base:string,workspace:string,view:string,tenant:string,panel='') {
  const query=new URLSearchParams({tenant,view});
  if(panel)query.set('panel',panel);
  return `${base}/${workspace}?${query}`;
}

export function sectionHref(base:string,section:string,tenant:string) {
  const location=legacyLocation(section);
  return workspaceHref(base,location.workspace,location.view,tenant,location.panel);
}

export function resolveWorkspace(section:string,view='',panel='') {
  const definition=workspaceDefinitions.find(item=>item.id===section);
  if(!definition){const legacy=legacyLocation(section);return {...legacy,section,panel:panel||legacy.panel||''};}
  const selected=definition.views.find(item=>item.id===view)||definition.views[0];
  if(section==='home'&&view==='application')return {workspace:'home',view,section:'application',panel};
  return {workspace:section,view:selected.id,section:selected.section,panel};
}
