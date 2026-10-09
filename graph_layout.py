"""Offline force layout and ranked subgraphs, inspired by graph exploration patterns."""
import math


def subset(nodes,edges,limit,focus=None):
    ids={n['id'] for n in nodes};adj={rid:set() for rid in ids};degree=dict.fromkeys(ids,0)
    for e in edges:
        a,b=e['source'],e['target']
        if a in ids and b in ids:
            adj[a].add(b);adj[b].add(a);degree[a]+=1;degree[b]+=1
    if focus in ids:
        allowed={focus}|adj[focus]
        nodes=[n for n in nodes if n['id'] in allowed]
    ordered=sorted(nodes,key=lambda n:(n['id']!=focus,not n.get('in_library',True),-degree[n['id']],not n.get('pdf'),n['id']))
    shown=ordered[:max(1,int(limit))];visible={n['id'] for n in shown}
    return shown,[e for e in edges if e['source'] in visible and e['target'] in visible]


def force_layout(nodes,edges):
    import numpy as np
    count=len(nodes)
    if not count:return {}
    if count==1:return {nodes[0]['id']:(0.,0.)}
    indexes={n['id']:i for i,n in enumerate(nodes)}
    rng=np.random.default_rng(42);pos=rng.uniform(-1,1,(count,2))*math.sqrt(count)*20
    pairs=np.array([(indexes[e['source']],indexes[e['target']]) for e in edges],dtype=int)
    ideal=52.;temperature=32.
    for step in range(80 if count<250 else 45):
        delta=pos[:,None,:]-pos[None,:,:];distance=np.maximum(np.linalg.norm(delta,axis=2),1.)
        force=(delta*(ideal**2/distance**2)[:,:,None]).sum(axis=1)
        if len(pairs):
            difference=pos[pairs[:,0]]-pos[pairs[:,1]];length=np.linalg.norm(difference,axis=1)
            attraction=difference*(length/ideal)[:,None]
            np.add.at(force,pairs[:,0],-attraction);np.add.at(force,pairs[:,1],attraction)
        force-=pos*.06
        norm=np.maximum(np.linalg.norm(force,axis=1),.1)
        pos+=force*(np.minimum(norm,temperature)/norm)[:,None];temperature*=.95
    pos-=pos.mean(axis=0)
    return {n['id']:tuple(map(float,pos[i])) for i,n in enumerate(nodes)}
