import itertools
from functools import reduce
import numpy as np

from OCP.Bnd import Bnd_Box
from OCP.BRep import BRep_Tool
from OCP.BRepBndLib import BRepBndLib
from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.BRepTools import BRepTools


from OCP.TopAbs import (
    TopAbs_VERTEX,
    TopAbs_EDGE,
    TopAbs_FACE,
)
from OCP.TopoDS import TopoDS_Shape, TopoDS_Compound, TopoDS_Solid
from OCP.TopAbs import TopAbs_FACE
from OCP.TopExp import TopExp_Explorer

from OCP.StlAPI import StlAPI_Writer

from cadquery import Compound
from cadquery.occ_impl.shapes import downcast
from .utils import distance

HASH_CODE_MAX = 2147483647


class BoundingBox(object):
    def __init__(self, obj=None, optimal=False, tol=1e-5):
        self.optimal = optimal
        self.tol = tol
        if obj is None:
            self.xmin = self.xmax = self.ymin = self.ymax = self.zmin = self.zmax = 0
        else:
            bbox = self._bounding_box(obj, tol)
            self.xmin, self.xmax, self.ymin, self.ymax, self.zmin, self.zmax = bbox
        self._calc()

    def _bounding_box(self, obj, tol=1e-5):
        bbox = Bnd_Box()
        if self.optimal:
            BRepTools.Clean_s(obj)
            BRepBndLib.AddOptimal_s(obj, bbox)
        else:
            BRepBndLib.Add_s(obj, bbox)
        values = bbox.Get()
        return (values[0], values[3], values[1], values[4], values[2], values[5])

    def _calc(self):
        self.xsize = self.xmax - self.xmin
        self.ysize = self.ymax - self.ymin
        self.zsize = self.zmax - self.zmin
        self.center = (
            self.xmin + self.xsize / 2.0,
            self.ymin + self.ysize / 2.0,
            self.zmin + self.zsize / 2.0,
        )
        self.max = max([abs(x) for x in (self.xmin, self.xmax, self.ymin, self.ymax, self.zmin, self.zmax)])

    def is_empty(self, eps=0.01):
        return (
            (abs(self.xmax - self.xmin) < 0.01)
            and (abs(self.ymax - self.ymin) < 0.01)
            and (abs(self.zmax - self.zmin) < 0.01)
        )

    def max_dist_from_center(self):
        return max(
            [
                distance(self.center, v)
                for v in itertools.product((self.xmin, self.xmax), (self.ymin, self.ymax), (self.zmin, self.zmax))
            ]
        )

    def max_dist_from_origin(self):
        return max(
            [
                np.linalg.norm(v)
                for v in itertools.product((self.xmin, self.xmax), (self.ymin, self.ymax), (self.zmin, self.zmax))
            ]
        )

    def update(self, bb):
        if isinstance(bb, BoundingBox):
            self.xmin = min(bb.xmin, self.xmin)
            self.xmax = max(bb.xmax, self.xmax)
            self.ymin = min(bb.ymin, self.ymin)
            self.ymax = max(bb.ymax, self.ymax)
            self.zmin = min(bb.zmin, self.zmin)
            self.zmax = max(bb.zmax, self.zmax)
        elif isinstance(bb, dict):
            self.xmin = min(bb["xmin"], self.xmin)
            self.xmax = max(bb["xmax"], self.xmax)
            self.ymin = min(bb["ymin"], self.ymin)
            self.ymax = max(bb["ymax"], self.ymax)
            self.zmin = min(bb["zmin"], self.zmin)
            self.zmax = max(bb["zmax"], self.zmax)
        else:
            raise "Wrong bounding box param"

        self._calc()

    def to_dict(self):
        return {
            "xmin": self.xmin,
            "xmax": self.xmax,
            "ymin": self.ymin,
            "ymax": self.ymax,
            "zmin": self.zmin,
            "zmax": self.zmax,
        }

    def __repr__(self):
        return "{xmin=%f, xmax=%f, ymin=%f, ymax=%f, zmin=%f, zmax=%f]" % (
            self.xmin,
            self.xmax,
            self.ymin,
            self.ymax,
            self.zmin,
            self.zmax,
        )


def bounding_box(objs, loc=None, optimal=False):
    if isinstance(objs, (list, tuple)):
        compound = Compound._makeCompound(objs)
    else:
        compound = objs

    return BoundingBox(compound if loc is None else compound.Moved(loc.wrapped), optimal=optimal)


# Export STL


def write_stl_file(compound, filename, tolerance=None, angular_tolerance=None):

    # Remove previous mesh data
    BRepTools.Clean_s(compound)

    mesh = BRepMesh_IncrementalMesh(compound, tolerance, True, angular_tolerance)
    mesh.Perform()

    writer = StlAPI_Writer()

    result = writer.Write(compound, filename)

    # Remove the mesh data again
    BRepTools.Clean_s(compound)
    return result


# OCP types and accessors

# Source pythonocc-core: Extend/TopologyUtils.py
def is_vertex(topods_shape):
    if not hasattr(topods_shape, "ShapeType"):
        return False
    return topods_shape.ShapeType() == TopAbs_VERTEX


# Source pythonocc-core: Extend/TopologyUtils.py
def is_edge(topods_shape):
    if not hasattr(topods_shape, "ShapeType"):
        return False
    return topods_shape.ShapeType() == TopAbs_EDGE


def is_compound(topods_shape):
    return isinstance(topods_shape, TopoDS_Compound)


def is_solid(topods_shape):
    return isinstance(topods_shape, TopoDS_Solid)


def is_shape(topods_shape):
    return isinstance(topods_shape, TopoDS_Shape)


def _get_topo(shape, topo):
    explorer = TopExp_Explorer(shape, topo)
    hashes = {}
    while explorer.More():
        item = explorer.Current()
        hash = item.HashCode(HASH_CODE_MAX)
        if hashes.get(hash) is None:
            hashes[hash] = True
            yield downcast(item)
        explorer.Next()


def get_faces(shape):
    return _get_topo(shape, TopAbs_FACE)


def get_edges(shape):
    return _get_topo(shape, TopAbs_EDGE)


def get_point(vertex):
    p = BRep_Tool.Pnt_s(vertex)
    return (p.X(), p.Y(), p.Z())


def loc_to_tq(loc):
    T = loc.wrapped.Transformation()
    t = T.Transforms()
    q = T.GetRotation()
    return (t, (q.X(), q.Y(), q.Z(), q.W()))


def get_rgb(color):
    if color is None:
        return (176, 176, 176)
    rgb = color.wrapped.GetRGB()
    return (int(255 * rgb.Red()), int(255 * rgb.Green()), int(255 * rgb.Blue()))


# def from_loc(loc):
#     t, q = loc_to_tq(loc)
#     return {"t": t, "q": q}


# def to_loc(t, q):
#     trsf = gp_Trsf()
#     trsf.SetRotation(gp_Quaternion(*q))
#     trsf.SetTranslationPart(gp_Vec(*t))

#     return Location(trsf)


# def to_rgb(color):
#     rgb = color.wrapped.GetRGB()
#     return (rgb.Red(), rgb.Green(), rgb.Blue())


# def from_rgb(r, g, b):
#     return Color(r, g, b)
