# A part of NonVisual Desktop Access (NVDA)
# Copyright (C) 2026 NV Access Limited
# This file may be used under the terms of the GNU General Public License, version 2 or later.
# For more details see: https://www.gnu.org/licenses/gpl-2.0.html

"""Unit tests for L{mouseHandler.getMouseTargetPoint}."""

import unittest

import controlTypes
import locationHelper
import mouseHandler
import textInfos
from textInfos.offsets import OffsetsTextInfo

from .textProvider import BasicTextInfo, BasicTextProvider


#: The location of the object the mouse is being routed to.
OBJ_RECT = locationHelper.RectLTWH(100, 100, 200, 100)
#: The centre of L{OBJ_RECT}, i.e. the expected point whenever the review position isn't usable.
OBJ_CENTRE = locationHelper.Point(200, 150)


class _CharacterRectTextInfo(BasicTextInfo):
	"""A TextInfo which reports a distinct bounding rectangle for every character.

	L{NVDAObjects.NVDAObjectTextInfo} overrides L{_get_boundingRects} to report the location of the
	whole object, so the offsets based implementation is restored here in order to exercise the
	per character path.
	"""

	#: Number of times bounding rectangles have been fetched, to prove when they aren't.
	boundingRectsFetchCount = 0

	def _get_boundingRects(self) -> list[locationHelper.RectLTWH]:
		type(self).boundingRectsFetchCount += 1
		if self.obj.boundingRectsError is not None:
			raise self.obj.boundingRectsError
		return OffsetsTextInfo._get_boundingRects(self)

	def _getBoundingRectFromOffset(self, offset: int) -> locationHelper.RectLTWH:
		try:
			return self.obj.characterRects[offset]
		except (TypeError, IndexError):
			raise LookupError(f"No rectangle for offset {offset}")


class _FakeTextObject(BasicTextProvider):
	"""A text provider with a controllable location, states and per character rectangles."""

	TextInfo = _CharacterRectTextInfo

	def __init__(
		self,
		objRect: locationHelper.RectLTWH | None = OBJ_RECT,
		characterRects: list[locationHelper.RectLTWH] | None = None,
		states: set[controlTypes.State] | None = None,
		locationError: Exception | None = None,
		boundingRectsError: Exception | None = None,
		text: str = "abcd",
	):
		super().__init__(text=text)
		self.objRect = objRect
		self.characterRects = characterRects
		self.fakeStates = states or set()
		self.locationError = locationError
		self.boundingRectsError = boundingRectsError

	def _get_location(self) -> locationHelper.RectLTWH | None:
		if self.locationError is not None:
			raise self.locationError
		return self.objRect

	def _get_states(self) -> set[controlTypes.State]:
		return self.fakeStates


class _WholeObjectTextInfo(BasicTextInfo):
	"""A TextInfo which reports the location of the whole object as its bounding rectangle.

	This is the shape of L{NVDAObjects.NVDAObjectTextInfo._get_boundingRects}, and therefore also of
	an element in a virtual buffer whose text originates from an ``aria-label`` rather than from
	L{IAccessibleText}, since L{virtualBuffers.VirtualBufferTextInfo._getBoundingRectFromOffset}
	falls back to the object's location in that case.
	"""

	def _get_boundingRects(self) -> list[locationHelper.RectLTWH]:
		return [self.obj.location]


class _WholeObjectTextObject(_FakeTextObject):
	TextInfo = _WholeObjectTextInfo


class GetMouseTargetPoint(unittest.TestCase):
	def setUp(self) -> None:
		_CharacterRectTextInfo.boundingRectsFetchCount = 0

	@staticmethod
	def _makeReviewPosition(obj: BasicTextProvider, offset: int = 0) -> textInfos.TextInfo:
		"""Create a collapsed review position at the given offset."""
		return obj.makeTextInfo(textInfos.offsets.Offsets(offset, offset))

	def test_characterRectWithinObjectUsesCharacterCentre(self):
		"""A character drawn inside the object routes to the centre of that character."""
		charRect = locationHelper.RectLTWH(150, 120, 20, 20)
		obj = _FakeTextObject(characterRects=[charRect] * 4)

		point = mouseHandler.getMouseTargetPoint(obj, self._makeReviewPosition(obj))

		self.assertEqual(point, locationHelper.Point(160, 130))
		# Regression test: the top left corner is frequently outside the hit target.
		self.assertNotEqual(point, charRect.toLTRB().topLeft)

	def test_characterRectIsWholeObjectUsesObjectCentre(self):
		"""Text with no rectangle of its own, e.g. an aria-label, routes to the object's centre.

		The virtual buffer reports the whole element's location for such text, so the centre of the
		"character" rectangle is the centre of the element.
		"""
		obj = _WholeObjectTextObject()

		point = mouseHandler.getMouseTargetPoint(obj, self._makeReviewPosition(obj))

		self.assertEqual(point, OBJ_CENTRE)
		# Regression test for the reported bug: this used to route to the element's top left corner.
		self.assertNotEqual(point, OBJ_RECT.toLTRB().topLeft)

	def test_characterRectOutsideObjectUsesObjectCentre(self):
		"""A label positioned outside the element it labels is ignored."""
		offscreenLabel = locationHelper.RectLTWH(-9999, 120, 20, 20)
		obj = _FakeTextObject(characterRects=[offscreenLabel] * 4)

		point = mouseHandler.getMouseTargetPoint(obj, self._makeReviewPosition(obj))

		self.assertEqual(point, OBJ_CENTRE)

	def test_characterRectAdjacentToObjectUsesObjectCentre(self):
		"""A character rectangle which only touches the object's right edge is ignored.

		Containment is half open, so a zero width intersection on the edge isn't within the object.
		"""
		adjacent = locationHelper.RectLTWH(OBJ_RECT.right, 120, 20, 20)
		obj = _FakeTextObject(characterRects=[adjacent] * 4)

		point = mouseHandler.getMouseTargetPoint(obj, self._makeReviewPosition(obj))

		self.assertEqual(point, OBJ_CENTRE)

	def test_offscreenTextObjectUsesObjectCentreWithoutFetchingRects(self):
		"""Text whose object is off screen is ignored, without paying for its bounding rectangles."""
		charRect = locationHelper.RectLTWH(150, 120, 20, 20)
		obj = _FakeTextObject(
			characterRects=[charRect] * 4,
			states={controlTypes.State.OFFSCREEN},
		)

		point = mouseHandler.getMouseTargetPoint(obj, self._makeReviewPosition(obj))

		self.assertEqual(point, OBJ_CENTRE)
		self.assertEqual(_CharacterRectTextInfo.boundingRectsFetchCount, 0)

	def test_invisibleTextObjectUsesObjectCentre(self):
		charRect = locationHelper.RectLTWH(150, 120, 20, 20)
		obj = _FakeTextObject(
			characterRects=[charRect] * 4,
			states={controlTypes.State.INVISIBLE},
		)

		point = mouseHandler.getMouseTargetPoint(obj, self._makeReviewPosition(obj))

		self.assertEqual(point, OBJ_CENTRE)

	def test_boundingRectsNotImplementedUsesObjectCentre(self):
		obj = _FakeTextObject(boundingRectsError=NotImplementedError)

		point = mouseHandler.getMouseTargetPoint(obj, self._makeReviewPosition(obj))

		self.assertEqual(point, OBJ_CENTRE)

	def test_boundingRectsLookupErrorUsesObjectCentre(self):
		obj = _FakeTextObject(boundingRectsError=LookupError)

		point = mouseHandler.getMouseTargetPoint(obj, self._makeReviewPosition(obj))

		self.assertEqual(point, OBJ_CENTRE)

	def test_noBoundingRectsUsesObjectCentre(self):
		"""No rectangles at all, e.g. because every offset raised, falls back to the object."""
		obj = _FakeTextObject(characterRects=None)

		point = mouseHandler.getMouseTargetPoint(obj, self._makeReviewPosition(obj))

		self.assertEqual(point, OBJ_CENTRE)

	def test_noReviewPositionUsesObjectCentre(self):
		obj = _FakeTextObject(characterRects=[locationHelper.RectLTWH(150, 120, 20, 20)] * 4)

		self.assertEqual(mouseHandler.getMouseTargetPoint(obj), OBJ_CENTRE)

	def test_objectWithoutLocationRaisesLookupError(self):
		obj = _FakeTextObject(objRect=None)

		with self.assertRaises(LookupError):
			mouseHandler.getMouseTargetPoint(obj, self._makeReviewPosition(obj))

	def test_objectWithEmptyLocationRaisesLookupError(self):
		obj = _FakeTextObject(objRect=locationHelper.RectLTWH(0, 0, 0, 0))

		with self.assertRaises(LookupError):
			mouseHandler.getMouseTargetPoint(obj, self._makeReviewPosition(obj))

	def test_locationErrorRaisesLookupError(self):
		"""An error while fetching the location, e.g. a COMError, is reported as a LookupError."""
		obj = _FakeTextObject(locationError=RuntimeError("Boom"))

		with self.assertRaises(LookupError):
			mouseHandler.getMouseTargetPoint(obj, self._makeReviewPosition(obj))

	def test_reviewPositionIsNotModified(self):
		"""The caller's review position must not be expanded in place."""
		obj = _FakeTextObject(characterRects=[locationHelper.RectLTWH(150, 120, 20, 20)] * 4)
		reviewPosition = self._makeReviewPosition(obj, offset=1)

		mouseHandler.getMouseTargetPoint(obj, reviewPosition)

		self.assertEqual(reviewPosition.offsets, (1, 1))
		self.assertTrue(reviewPosition.isCollapsed)
