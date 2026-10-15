"""Pure geometry for named graph selections; only visible paper nodes are selected."""
def region_members(points, start, end, shape='rectangle'):
    x1,x2=sorted((start[0],end[0]));y1,y2=sorted((start[1],end[1]))
    if x2-x1<2 or y2-y1<2:return []
    cx,cy=(x1+x2)/2,(y1+y2)/2;rx,ry=(x2-x1)/2,(y2-y1)/2
    return [rid for rid,(x,y) in points.items() if x1<=x<=x2 and y1<=y<=y2 and
            (shape!='ellipse' or ((x-cx)/rx)**2+((y-cy)/ry)**2<=1.0000001)]
