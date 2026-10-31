from __future__ import annotations

from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import QPainter, QImage, QPixmap, QColor, QPen, QBrush
from PySide6.QtWidgets import QWidget


class PreviewCanvas(QWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setMinimumSize(400, 260)
        self._pixmap_original: QPixmap | None = None
        self._pixmap_original: QPixmap | None = None
        self._pixmap_result: QPixmap | None = None
        self._pixmaps: dict[str, QPixmap | None] = {
            "original": None,
            "cutout": None,
            "alpha": None,
            "fg": None,
            "checker": None,
            "hint": None,
        }
        self._view_mode: str = "split_v"
        self._split_ratio_x: float = 0.5
        self._split_ratio_y: float = 0.5
        self._overlay_opacity: float = 0.5
        self._primary_key: str = "original"
        self._secondary_key: str = "cutout"
        self._swapped: bool = False
        self._is_dragging_split_x: bool = False
        self._is_dragging_split_y: bool = False
        self._status_text: str = "Drop video here to inspect"

        self.setMouseTracking(True)
        self.setStyleSheet("background-color: #0b0f14; border-radius: 6px; border: 1px solid #21262d;")

        # zoom & pan state
        self._zoom_scale: float = 1.0
        self._zoom_mode: str = "fit" # "fit", "100%", "200%", "custom"
        self._pan_offset: QPointF = QPointF(0, 0)
        self._is_panning: bool = False
        self._last_mouse_pos: QPointF = QPointF(0, 0)
        self._target_rect: QRectF = QRectF(0, 0, 0, 0)

    def set_frames(self, original_pixmap: QPixmap | None, result_pixmap: QPixmap | None):
        self._pixmap_original = original_pixmap
        self._pixmap_result = result_pixmap
        self._pixmaps["original"] = original_pixmap
        self._pixmaps["cutout"] = result_pixmap
        self._status_text = ""
        self.update()

    def set_all_pixmaps(self, pixmaps: dict[str, QPixmap | None]):
        self._pixmaps.update(pixmaps)
        if "original" in pixmaps and pixmaps["original"] is not None:
            self._pixmap_original = pixmaps["original"]
        if "cutout" in pixmaps and pixmaps["cutout"] is not None:
            self._pixmap_result = pixmaps["cutout"]
        self._status_text = ""
        self.update()

    def set_view_mode(self, mode: str):
        if mode == "split":
            mode = "split_v"
        self._view_mode = mode
        self.update()

    def set_swapped(self, swapped: bool):
        self._swapped = swapped
        self.update()

    def toggle_swap(self):
        self._swapped = not self._swapped
        self.update()

    def set_overlay_opacity(self, opacity: float):
        self._overlay_opacity = max(0.0, min(1.0, float(opacity)))
        self.update()

    def set_comparison_pairs(self, primary: str, secondary: str):
        self._primary_key = primary
        self._secondary_key = secondary
        self.update()

    def set_buffer_a(self, key: str):
        self._primary_key = key
        self.update()

    def set_buffer_b(self, key: str):
        self._secondary_key = key
        self.update()

    def get_buffer_a(self) -> str:
        return self._primary_key

    def get_buffer_b(self) -> str:
        return self._secondary_key

    def is_swapped(self) -> bool:
        return self._swapped

    def set_status_text(self, text: str):
        self._status_text = text
        self.update()

    def set_zoom_mode(self, mode: str):
        self._zoom_mode = mode
        if mode in ("fit", "100%"):
            self._zoom_scale = 1.0
            self._pan_offset = QPointF(0, 0)
        elif mode == "200%":
            self._zoom_scale = 2.0
            self._pan_offset = QPointF(0, 0)
        self.update()

    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        if delta != 0:
            factor = 1.15 if delta > 0 else (1.0 / 1.15)
            new_scale = max(0.2, min(8.0, self._zoom_scale * factor))
            self._zoom_scale = new_scale
            self._zoom_mode = "custom"
            self.update()
        super().wheelEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.MiddleButton or (
            event.button() == Qt.MouseButton.LeftButton and event.modifiers() & Qt.KeyboardModifier.ControlModifier
        ):
            self._is_panning = True
            self._last_mouse_pos = event.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return

        if event.button() == Qt.MouseButton.LeftButton and self._target_rect.width() > 0:
            if self._view_mode in ("split_v", "split"):
                split_x = self._target_rect.x() + self._target_rect.width() * self._split_ratio_x
                if abs(event.position().x() - split_x) <= 14:
                    self._is_dragging_split_x = True
                    event.accept()
                    return
                elif self._target_rect.contains(event.position()):
                    ratio = (event.position().x() - self._target_rect.x()) / self._target_rect.width()
                    self._split_ratio_x = max(0.0, min(1.0, ratio))
                    self._is_dragging_split_x = True
                    self.update()
                    event.accept()
                    return

            elif self._view_mode == "split_h":
                split_y = self._target_rect.y() + self._target_rect.height() * self._split_ratio_y
                if abs(event.position().y() - split_y) <= 14:
                    self._is_dragging_split_y = True
                    event.accept()
                    return
                elif self._target_rect.contains(event.position()):
                    ratio = (event.position().y() - self._target_rect.y()) / self._target_rect.height()
                    self._split_ratio_y = max(0.0, min(1.0, ratio))
                    self._is_dragging_split_y = True
                    self.update()
                    event.accept()
                    return

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._is_panning:
            delta = event.position() - self._last_mouse_pos
            self._pan_offset += delta
            self._last_mouse_pos = event.position()
            self.update()
            event.accept()
            return

        if self._is_dragging_split_x:
            if self._target_rect.width() > 0:
                ratio = (event.position().x() - self._target_rect.x()) / self._target_rect.width()
                self._split_ratio_x = max(0.0, min(1.0, ratio))
                self.update()
                event.accept()
                return

        if self._is_dragging_split_y:
            if self._target_rect.height() > 0:
                ratio = (event.position().y() - self._target_rect.y()) / self._target_rect.height()
                self._split_ratio_y = max(0.0, min(1.0, ratio))
                self.update()
                event.accept()
                return

        if self._view_mode in ("split_v", "split") and self._target_rect.width() > 0:
            split_x = self._target_rect.x() + self._target_rect.width() * self._split_ratio_x
            if abs(event.position().x() - split_x) <= 14 and self._target_rect.top() <= event.position().y() <= self._target_rect.bottom():
                self.setCursor(Qt.CursorShape.SplitHCursor)
            else:
                self.setCursor(Qt.CursorShape.ArrowCursor)
        elif self._view_mode == "split_h" and self._target_rect.height() > 0:
            split_y = self._target_rect.y() + self._target_rect.height() * self._split_ratio_y
            if abs(event.position().y() - split_y) <= 14 and self._target_rect.left() <= event.position().x() <= self._target_rect.right():
                self.setCursor(Qt.CursorShape.SplitVCursor)
            else:
                self.setCursor(Qt.CursorShape.ArrowCursor)
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._is_panning:
            self._is_panning = False
            self.setCursor(Qt.CursorShape.ArrowCursor)
            event.accept()
            return
        if self._is_dragging_split_x:
            self._is_dragging_split_x = False
            self.setCursor(Qt.CursorShape.ArrowCursor)
            event.accept()
            return
        if self._is_dragging_split_y:
            self._is_dragging_split_y = False
            self.setCursor(Qt.CursorShape.ArrowCursor)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def _draw_checkerboard(self, painter: QPainter, rect: QRectF):
        cell_size = 14
        c1 = QColor(28, 32, 38)
        c2 = QColor(38, 44, 52)
        painter.save()
        painter.setClipRect(rect)
        cols = int(rect.width() // cell_size) + 3
        rows = int(rect.height() // cell_size) + 3
        for r in range(rows):
            for c in range(cols):
                color = c1 if (r + c) % 2 == 0 else c2
                painter.fillRect(
                    QRectF(rect.x() + c * cell_size, rect.y() + r * cell_size, cell_size, cell_size),
                    color
                )
        painter.restore()

    def _get_buffer(self, key: str) -> QPixmap | None:
        if key == "original":
            return self._pixmaps.get("original") or self._pixmap_original
        if key in ("cutout", "result"):
            return self._pixmaps.get("cutout") or self._pixmap_result
        if key == "checker":
            return self._pixmaps.get("checker")
        if key == "alpha":
            return self._pixmaps.get("alpha")
        if key == "fg":
            return self._pixmaps.get("fg")
        if key == "hint":
            return self._pixmaps.get("hint")
        return self._pixmaps.get(key)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        w, h = self.width(), self.height()

        ref_pixmap = (
            self._get_buffer("original")
            or self._get_buffer("cutout")
            or self._get_buffer("checker")
            or self._get_buffer("fg")
            or self._get_buffer("alpha")
        )

        if ref_pixmap is None:
            self._target_rect = QRectF(0, 0, 0, 0)
            box_w = min(400, max(260, w - 40))
            box_h = 90
            box_rect = QRectF((w - box_w) / 2, (h - box_h) / 2, box_w, box_h)

            painter.setPen(QPen(QColor(45, 52, 60), 1, Qt.PenStyle.DashLine))
            painter.setBrush(QBrush(QColor(22, 26, 30)))
            painter.drawRoundedRect(box_rect, 6, 6)

            font = painter.font()
            font.setPointSize(11)
            font.setBold(True)
            painter.setFont(font)
            painter.setPen(QColor(200, 206, 214))
            painter.drawText(QRectF(box_rect.x(), box_rect.y() + 20, box_rect.width(), 24), Qt.AlignmentFlag.AlignCenter, "Drop video here to inspect")

            font.setPointSize(10)
            font.setBold(False)
            painter.setFont(font)
            painter.setPen(QColor(120, 128, 138))
            painter.drawText(QRectF(box_rect.x(), box_rect.y() + 48, box_rect.width(), 20), Qt.AlignmentFlag.AlignCenter, "Supports MP4, MOV, MKV, WebM, AVI")
            return

        base_size = ref_pixmap.size().scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio)
        w_scaled = base_size.width() * self._zoom_scale
        h_scaled = base_size.height() * self._zoom_scale
        x = (w - w_scaled) / 2 + self._pan_offset.x()
        y = (h - h_scaled) / 2 + self._pan_offset.y()
        self._target_rect = QRectF(x, y, w_scaled, h_scaled)
        target_rect = self._target_rect

        buf_a_key = self._secondary_key if self._swapped else self._primary_key
        buf_b_key = self._primary_key if self._swapped else self._secondary_key

        pm_a = self._get_buffer(buf_a_key)
        pm_b = self._get_buffer(buf_b_key)
        if pm_b is None:
            pm_b = self._get_buffer("cutout") or self._get_buffer("checker")

        if self._view_mode == "single":
            if buf_a_key in ("cutout", "checker"):
                self._draw_checkerboard(painter, target_rect)
            if pm_a:
                painter.drawPixmap(target_rect.toRect(), pm_a)

        elif self._view_mode in ("original", "plate"):
            pm = self._get_buffer("original")
            if pm:
                painter.drawPixmap(target_rect.toRect(), pm)

        elif self._view_mode in ("alpha", "matte"):
            pm = self._get_buffer("alpha")
            if pm:
                painter.drawPixmap(target_rect.toRect(), pm)
            elif pm_b:
                self._draw_checkerboard(painter, target_rect)
                painter.drawPixmap(target_rect.toRect(), pm_b)

        elif self._view_mode == "fg":
            pm = self._get_buffer("fg") or self._get_buffer("original")
            if pm:
                painter.drawPixmap(target_rect.toRect(), pm)

        elif self._view_mode in ("checker", "composite"):
            self._draw_checkerboard(painter, target_rect)
            pm = self._get_buffer("cutout") or self._get_buffer("checker")
            if pm:
                painter.drawPixmap(target_rect.toRect(), pm)

        elif self._view_mode == "cutout":
            self._draw_checkerboard(painter, target_rect)
            pm = self._get_buffer("cutout")
            if pm:
                painter.drawPixmap(target_rect.toRect(), pm)

        elif self._view_mode in ("split_v", "split"):
            split_x = target_rect.x() + target_rect.width() * self._split_ratio_x
            left_width = split_x - target_rect.x()
            right_width = target_rect.right() - split_x

            if right_width > 0:
                right_rect = QRectF(split_x, target_rect.y(), right_width, target_rect.height())
                self._draw_checkerboard(painter, right_rect)

            if pm_a and left_width > 0:
                painter.save()
                painter.setClipRect(QRectF(target_rect.x(), target_rect.y(), left_width, target_rect.height()))
                painter.drawPixmap(target_rect.toRect(), pm_a)
                painter.restore()

            if pm_b and right_width > 0:
                painter.save()
                painter.setClipRect(QRectF(split_x, target_rect.y(), right_width, target_rect.height()))
                painter.drawPixmap(target_rect.toRect(), pm_b)
                painter.restore()
            elif not pm_b and right_width > 0:
                painter.save()
                font = painter.font()
                font.setPointSize(10)
                painter.setFont(font)
                painter.setPen(QColor(160, 168, 178, 180))
                painter.drawText(QRectF(split_x, target_rect.y(), right_width, target_rect.height()), Qt.AlignmentFlag.AlignCenter, "Cutout Preview\n(Run keying to generate)")
                painter.restore()

            painter.setPen(QPen(QColor(230, 235, 245), 2))
            painter.drawLine(QPointF(split_x, target_rect.y()), QPointF(split_x, target_rect.bottom()))

            center_y = target_rect.y() + target_rect.height() / 2
            painter.setBrush(QBrush(QColor(240, 244, 250)))
            painter.setPen(QPen(QColor(30, 34, 40), 1.5))
            painter.drawEllipse(QPointF(split_x, center_y), 6, 6)

        elif self._view_mode == "split_h":
            split_y = target_rect.y() + target_rect.height() * self._split_ratio_y
            top_height = split_y - target_rect.y()
            bottom_height = target_rect.bottom() - split_y

            if bottom_height > 0:
                bottom_rect = QRectF(target_rect.x(), split_y, target_rect.width(), bottom_height)
                self._draw_checkerboard(painter, bottom_rect)

            if pm_a and top_height > 0:
                painter.save()
                painter.setClipRect(QRectF(target_rect.x(), target_rect.y(), target_rect.width(), top_height))
                painter.drawPixmap(target_rect.toRect(), pm_a)
                painter.restore()

            if pm_b and bottom_height > 0:
                painter.save()
                painter.setClipRect(QRectF(target_rect.x(), split_y, target_rect.width(), bottom_height))
                painter.drawPixmap(target_rect.toRect(), pm_b)
                painter.restore()

            painter.setPen(QPen(QColor(230, 235, 245), 2))
            painter.drawLine(QPointF(target_rect.x(), split_y), QPointF(target_rect.right(), split_y))

            center_x = target_rect.x() + target_rect.width() / 2
            painter.setBrush(QBrush(QColor(240, 244, 250)))
            painter.setPen(QPen(QColor(30, 34, 40), 1.5))
            painter.drawEllipse(QPointF(center_x, split_y), 6, 6)

        elif self._view_mode == "difference":
            painter.fillRect(target_rect, QColor(0, 0, 0))
            if pm_a and pm_b:
                painter.save()
                painter.drawPixmap(target_rect.toRect(), pm_a)
                painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Difference)
                painter.drawPixmap(target_rect.toRect(), pm_b)
                painter.restore()
            elif pm_a:
                painter.drawPixmap(target_rect.toRect(), pm_a)

        elif self._view_mode == "overlay":
            self._draw_checkerboard(painter, target_rect)
            if pm_a:
                painter.drawPixmap(target_rect.toRect(), pm_a)
            if pm_b:
                painter.save()
                painter.setOpacity(self._overlay_opacity)
                painter.drawPixmap(target_rect.toRect(), pm_b)
                painter.restore()

        else:
            if pm_b:
                self._draw_checkerboard(painter, target_rect)
                painter.drawPixmap(target_rect.toRect(), pm_b)
            elif pm_a:
                painter.drawPixmap(target_rect.toRect(), pm_a)

        if self._zoom_mode != "fit" or abs(self._zoom_scale - 1.0) > 1e-3:
            zoom_text = f"{int(self._zoom_scale * 100)}%"
            painter.setPen(QColor(140, 148, 160))
            painter.drawText(QRectF(10, h - 22, 60, 16), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, zoom_text)
