"""
simplify.py is a simple port of simplify.js by Vladimir Agafonkin
(https://github.com/mourner/simplify-js)

It uses a combination of Douglas-Peucker and Radial Distance algorithms.
"""

try:
    rangefunc = xrange
except NameError:
    rangefunc = range


def defaultAccessor(sequence, index, **kwargs):
    """
    given a sequence of objects and an index, return a sequence
    of 2 (2D) or 3 coordinates (3D) of the object.
    Extraneous values are ignored.

    Any extra kwargs to simplify() are passed to this function.
    """
    # if 'argToAccessor' in kwargs:
    #     print(kwargs['argToAccessor'])
    return sequence[index]


class Simplify(object):
    def getSquareDistance2d(self, points, p1, p2, **kwargs):
        """
        Square distance between two points (x,y)
        """
        (p1_0, p1_1, *_) = self.get(points, p1, **kwargs)
        (p2_0, p2_1, *_) = self.get(points, p2, **kwargs)
        dx = p1_0 - p2_0
        dy = p1_1 - p2_1
        return dx * dx + dy * dy

    def getSquareDistance3d(self, points, p1, p2, **kwargs):
        """
        Square distance between two points (x,y,z)
        """

        (p1_0, p1_1, p1_2, *_) = self.get(points, p1, **kwargs)
        (p2_0, p2_1, p2_2, *_) = self.get(points, p2, **kwargs)

        dx = p1_0 - p2_0
        dy = p1_1 - p2_1
        dz = p1_2 - p2_2
        return dx * dx + dy * dy + dz * dz

    def getSquareSegmentDistance2d(self, points, p, p1, p2, **kwargs):
        """
        Square distance between point and a segment
        """
        (x, y, *_) = self.get(points, p1, **kwargs)
        (p2_0, p2_1, *_) = self.get(points, p2, **kwargs)
        (p_0, p_1, *_) = self.get(points, p, **kwargs)

        dx = p2_0 - x
        dy = p2_1 - y

        if dx or dy:
            t = ((p_0 - x) * dx + (p_1 - y) * dy) / (dx * dx + dy * dy)

            if t > 1:
                x = p2_0
                y = p2_1
            elif t > 0:
                x += dx * t
                y += dy * t

        dx = p_0 - x
        dy = p_1 - y
        return dx * dx + dy * dy

    def getSquareSegmentDistance3d(self, points, p, p1, p2, **kwargs):
        """
        Square distance between point and a segment
        """
        (x, y, z, *_) = self.get(points, p1, **kwargs)
        (p2_0, p2_1, p2_2, *_) = self.get(points, p2, **kwargs)

        dx = p2_0 - x
        dy = p2_1 - y
        dz = p2_2 - z

        (p_0, p_1, p_2, *_) = self.get(points, p, **kwargs)

        if dx or dy:
            t = ((p_0 - x) * dx + (p_1 - y) * dy + (p_2 - z) * dz) / (
                dx * dx + dy * dy + dz * dz
            )

            if t > 1:
                x = p2_0
                y = p2_1
                z = p2_2
            elif t > 0:
                x += dx * t
                y += dy * t
                z += dz * t

        dx = p_0 - x
        dy = p_1 - y
        dz = p_2 - z
        return dx * dx + dy * dy + dz * dz

    def simplifyRadialDistance(self, points, point_range, tolerance, **kwargs):

        first = point_range[0]
        last = point_range[-1]
        prev_point = 0
        markers = [0]

        for i in point_range:  # rangefunc(first, last):

            if self.getSquareDistance(points, i, prev_point, **kwargs) > tolerance:
                markers.append(i)
                prev_point = i

        if prev_point != i:
            markers.append(i)
        return markers

    def simplifyDouglasPeucker(self, points, point_range, tolerance, **kwargs):

        first = point_range[0]
        last = point_range[-1]

        first_stack = []
        last_stack = []

        markers = [first, last]

        while last:
            max_sqdist = 0

            for i in rangefunc(first, last):
                sqdist = self.getSquareSegmentDistance(points, i, first, last, **kwargs)

                if sqdist > max_sqdist:
                    index = i
                    max_sqdist = sqdist

            if max_sqdist > tolerance:
                markers.append(index)

                first_stack.append(first)
                last_stack.append(index)

                first_stack.append(index)
                last_stack.append(last)

            # Can pop an empty array in Javascript, but not Python,
            # so check the list first
            first = first_stack.pop() if first_stack else None
            last = last_stack.pop() if last_stack else None

        markers.sort()
        return markers

    def simplify(
        self, points, tolerance=0.1, highestQuality=True, returnMarkers=False, **kwargs
    ):
        """
        Simplifies a sequence of points.

        `points`: A sequences of objects containing coordinates in some shape or form. The algorithm requires
        an accessor method as instantiation parameter. See the documentation of defaultAccessor for details.

        `tolerance (optional, 0.1 by default)`: Affects the amount of simplification that occurs (the smaller, the less simplification).

        `highestQuality (optional, True by default)`: Flag to exclude the distance pre-processing. Produces higher quality results, but runs slower.

        `returnMarkers`: if set, return a list of ints denoting the sequence elements in the simplified list.
        By default, return a list of objects taken from the original sequence.

        `kwargs`: Any extra keyword arguments are passed to the accessor function.
        """
        sqtolerance = tolerance * tolerance
        markers = list(range(0, len(points)))

        if not highestQuality:
            markers = self.simplifyRadialDistance(
                points, markers, sqtolerance, **kwargs
            )

        markers = self.simplifyDouglasPeucker(points, markers, sqtolerance, **kwargs)

        if returnMarkers:
            return markers
        else:
            return [points[i] for i in markers]


class Simplify3D(Simplify):
    def __init__(self, accessor=defaultAccessor):
        self.get = accessor
        self.getSquareDistance = self.getSquareDistance3d
        self.getSquareSegmentDistance = self.getSquareSegmentDistance3d


class Simplify2D(Simplify):
    def __init__(self, accessor=defaultAccessor):
        self.get = accessor
        self.getSquareDistance = self.getSquareDistance2d
        self.getSquareSegmentDistance = self.getSquareSegmentDistance2d


def featureAccessor(sequence, index, **kwargs):
    """
    accessor for a FeatureCollection of point features
    """
    return sequence[index].geometry.coordinates


if __name__ == "__main__":

    tolerance = 0.01
    highestQuality = False

    import geojson

    # contains a FeatureCollection of Points
    fn = "radiosonde.geojson"
    with open(fn, "r") as file:
        s = file.read()
        gj = geojson.loads(s.encode("utf8"))

    # the data structure of the original code:
    # a list of triplets (lat, lon, alt)
    points = list()
    i = 0
    for f in gj.features:
        coord = f.geometry.coordinates
        coord.append(i)
        points.append(coord)
        i += 1

    # this format can be handled by the default accessor
    s = Simplify3D()
    r = s.simplify(
        points,
        tolerance=tolerance,
        highestQuality=highestQuality,
        returnMarkers=True,
        argToAccessor="demo",
    )  # passed to accessor

    print(f"from {len(gj.features)} -> {len(r)}: markers={r}")

    # now use a custom accessor to directly access
    # the points of the FeatureCollection
    s2 = Simplify3D(accessor=featureAccessor)
    r = s2.simplify(
        gj.features,
        tolerance=tolerance,
        highestQuality=highestQuality,
        returnMarkers=False,
    )
    print(f"from {len(gj.features)} -> {len(r)}: points={r}")

    import timeit

    iterations = 10000
    secs = timeit.timeit(
        lambda: s2.simplify(
            gj.features, tolerance=tolerance, highestQuality=highestQuality
        ),
        number=iterations,
    )
    d = (secs / iterations) * 1e6
    print(
        f"time to simplify {len(gj.features)} points: {d:.0f} uS ({d/len(gj.features):.0f} uS/point)"
    )
