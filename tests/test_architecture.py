import hashlib
import importlib.util
from pathlib import Path
import struct
import tempfile
import unittest
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
SPEC=importlib.util.spec_from_file_location('architecture',ROOT/'tools/render-architecture.py')
a=importlib.util.module_from_spec(SPEC)
import sys
sys.modules[SPEC.name]=a
SPEC.loader.exec_module(a)

class ArchitectureTests(unittest.TestCase):
    def test_ownership_does_not_change_either_topology(self):
        for view in ['runtime','repositories']:
            reference=None
            for component in a.COMPONENTS:
                text=a.model(component,view)
                edges=[line for line in text.splitlines()if ' -> ' in line]
                if reference is None:reference=edges
                self.assertEqual(edges,reference)

    def test_runtime_assigns_in_postgres_and_keeps_devices_off_broker(self):
        d=a.runtime();edges={(e.source,e.target)for e in d.links}
        self.assertIn(('workers','api'),edges)
        self.assertIn(('api','postgres'),edges)
        self.assertIn(('api','artifacts'),edges)
        self.assertNotIn(('workers','postgres'),edges)
        self.assertNotIn(('workers','broker'),edges)
        self.assertFalse(any(b.owner in ['protocol','platform']for b in d.boxes))
        php=next(b for b in d.boxes if b.id=='router_php')
        self.assertEqual((php.owner,php.parent),('worker-portable','router'))

    def test_repository_arrows_are_usage_dependencies(self):
        edges={(e.source,e.target,e.kind)for e in a.repositories().links}
        self.assertIn(('worker-routeros','worker-portable','dependency'),edges)
        for name in ['gateway','worker-portable','worker-android']:
            self.assertIn((name,'protocol','dependency'),edges)
        self.assertNotIn(('worker-routeros','worker-portable','call'),edges)

    def test_routes_connect_box_boundaries_and_do_not_cross_unrelated_nodes(self):
        def boundary(point,b):
            x,y=point
            return (x in [b.x,b.x+b.w]and b.y<=y<=b.y+b.h)or(y in [b.y,b.y+b.h]and b.x<=x<=b.x+b.w)
        for d in [a.runtime(),a.repositories()]:
            boxes={b.id:b for b in d.boxes}
            for b in d.boxes:
                self.assertGreaterEqual(b.x,0);self.assertGreaterEqual(b.y,0)
                self.assertLessEqual(b.x+b.w,d.width);self.assertLessEqual(b.y+b.h,d.height)
            for e in d.links:
                self.assertTrue(boundary(e.points[0],boxes[e.source]),(e.source,e.points[0]))
                self.assertTrue(boundary(e.points[-1],boxes[e.target]),(e.target,e.points[-1]))
                for (x1,y1),(x2,y2)in zip(e.points,e.points[1:]):
                    self.assertTrue(x1==x2 or y1==y2)
                    for b in d.boxes:
                        if b.kind=='group'or b.id in [e.source,e.target]:continue
                        crosses=(y1==y2 and b.y<y1<b.y+b.h and max(min(x1,x2),b.x)<min(max(x1,x2),b.x+b.w))or(x1==x2 and b.x<x1<b.x+b.w and max(min(y1,y2),b.y)<min(max(y1,y2),b.y+b.h))
                        self.assertFalse(crosses,(e.source,e.target,b.id))

    def test_svg_is_safe_and_context_selects_one_package(self):
        ns={'s':'http://www.w3.org/2000/svg'}
        for component in a.COMPONENTS:
            for view in ['runtime','repositories']:
                root=ET.fromstring(a.svg(component,view))
                self.assertEqual(root.get('role'),'img')
                for tag in ['script','image','foreignObject']:
                    self.assertFalse(root.findall('.//s:'+tag,ns))
                if view=='repositories':
                    owned=[g for g in root.findall('s:g',ns)if g.get('data-owned')=='true']
                    self.assertEqual([g.get('id')for g in owned],[component])

    def test_both_checked_in_pngs_match_current_vectors_and_native_dimensions(self):
        for view,stem in [('runtime','architecture'),('repositories','repositories')]:
            raw=(ROOT/'docs'/(stem+'.png')).read_bytes()
            self.assertEqual(raw[:8],b'\x89PNG\r\n\x1a\n')
            self.assertEqual(struct.unpack('>II',raw[16:24]),(a.scene(view).width,a.scene(view).height))
            self.assertIn(b'fleet-svg-sha256\0'+hashlib.sha256((ROOT/'docs'/(stem+'.svg')).read_bytes()).hexdigest().encode(),raw)

if __name__=='__main__':unittest.main()
