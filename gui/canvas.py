from __future__ import annotations

from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import QPainter, QImage, QPixmap, QColor, QPen, QBrush
from PySide6.QtWidgets import QWidget


class PreviewCanvas(QWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setMinimumSize(400, 260)
        self._pixmap_original: QPixmap | None = None
        self._pixmap_result: QPixmap | None = None
        self._pixmaps: dict[str, QPixmap | None] = {
            "original": None,
            "cutout": None,
            "alpha": None,
            "fg": None,
            "checker": None,
        }
        self._view_mode: str = "split" # "split", "checker", "alpha", "fg", "original"
        self._split_ratio: float = 0.5
        self._is_dragging_split: bool = False
        self._status_text: str = "Drag and drop video here"

        self.setMouseTracking(True)
        self.setStyleSheet("background-color: #070707; border-radius: 4px; border: 1px solid #161616;")

        # zoom & pan state
        self._zoom_scale: float = 1.0
        self._zoom_mode: str = "fit" # "fit", "100%", "200%", "custom"
        self._pan_offset: QPointF = QPointF(0, 0)
        self._is_panning: bool = False
        self._last_mouse_pos: QPointF = QPointF(0, 0)

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
        self._view_mode = mode
        self.update()

    def set_status_text(self, text: str):
        self._status_text = text
        self.update()

    def set_zoom_mode(self, mode: str):
        self._zoom_mode = mode
        if mode == "fit":
            self._zoom_scale = 1.0
            self._pan_offset = QPointF(0, 0)
        elif mode == "100%":
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
        if event.button() == Qt.MouseButton.MiddleButton or (event.button() == Qt.MouseButton.LeftButton and event.modifiers() & Qt.KeyboardModifier.ControlModifier):
            self._is_panning = True
            self._last_mouse_pos = event.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return

        if self._view_mode == "split" and event.button() == Qt.MouseButton.LeftButton:
            x_norm = event.position().x() / max(1, self.width())
            if abs(x_norm - self._split_ratio) < 0.05:
                self._is_dragging_split = True
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

        if self._is_dragging_split:
            self._split_ratio = max(0.05, min(0.95, event.position().x() / max(1, self.width())))
            self.update()
            event.accept()
            return
        elif self._view_mode == "split":
            x_norm = event.position().x() / max(1, self.width())
            if abs(x_norm - self._split_ratio) < 0.05:
                self.setCursor(Qt.CursorShape.SplitHCursor)
            else:
                self.setCursor(Qt.CursorShape.ArrowCursor)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._is_panning:
            self._is_panning = False
            self.setCursor(Qt.CursorShape.ArrowCursor)
            event.accept()
            return
        if self._is_dragging_split:
            self._is_dragging_split = False
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def _draw_checkerboard(self, painter: QPainter, rect: QRectF):
        cell_size = 16
        c1 = QColor(36, 40, 46)
        c2 = QColor(48, 54, 62)
        cols = int(rect.width() // cell_size) + 2
        rows = int(rect.height() // cell_size) + 2
        for r in range(rows):
            for c in range(cols):
                color = c1 if (r + c) % 2 == 0 else c2
                painter.fillRect(
                    QRectF(rect.x() + c * cell_size, rect.y() + r * cell_size, cell_size, cell_size),
                    color
                )

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        w, h = self.width(), self.height()

        ref_pixmap = (
            self._pixmaps.get("original")
            or self._pixmaps.get("cutout")
            or self._pixmaps.get("checker")
            or self._pixmaps.get("fg")
            or self._pixmaps.get("alpha")
            or self._pixmap_original
            or self._pixmap_result
        )

        if ref_pixmap is None:
            painter.setPen(QColor(140, 148, 160))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self._status_text)
            return

        # fit inside canvas keeping aspect ratio and apply zoom / pan
        base_size = ref_pixmap.size().scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio)
        w_scaled = base_size.width() * self._zoom_scale
        h_scaled = base_size.height() * self._zoom_scale
        x = (w - w_scaled) / 2 + self._pan_offset.x()
        y = (h - h_scaled) / 2 + self._pan_offset.y()
        target_rect = QRectF(x, y, w_scaled, h_scaled)

        pm_orig = self._pixmaps.get("original") or self._pixmap_original
        pm_cutout = self._pixmaps.get("cutout") or self._pixmap_result
        pm_checker = self._pixmaps.get("checker")
        pm_alpha = self._pixmaps.get("alpha")
        pm_fg = self._pixmaps.get("fg")

        if self._view_mode == "original":
            if pm_orig:
                painter.drawPixmap(target_rect.toRect(), pm_orig)

        elif self._view_mode == "alpha":
            if pm_alpha:
                painter.drawPixmap(target_rect.toRect(), pm_alpha)
            elif pm_cutout:
                self._draw_checkerboard(painter, target_rect)
                painter.drawPixmap(target_rect.toRect(), pm_cutout)

        elif self._view_mode == "fg":
            if pm_fg:
                painter.drawPixmap(target_rect.toRect(), pm_fg)
            elif pm_orig:
                painter.drawPixmap(target_rect.toRect(), pm_orig)

        elif self._view_mode == "checker":
            self._draw_checkerboard(painter, target_rect)
            if pm_cutout:
                painter.drawPixmap(target_rect.toRect(), pm_cutout)
            elif pm_checker:
                painter.drawPixmap(target_rect.toRect(), pm_checker)

        elif self._view_mode == "split":
            split_x = target_rect.x() + target_rect.width() * self._split_ratio
            right_width = target_rect.x() + target_rect.width() - split_x

            # checkerboard background strictly under transparent right side
            if right_width > 0:
                right_rect = QRectF(split_x, target_rect.y(), right_width, target_rect.height())
                self._draw_checkerboard(painter, right_rect)

            # draw original clipped to left
            if pm_orig:
                painter.save()
                painter.setClipRect(QRectF(target_rect.x(), target_rect.y(), target_rect.width() * self._split_ratio, target_rect.height()))
                painter.drawPixmap(target_rect.toRect(), pm_orig)
                painter.restore()

            # draw keyed result clipped to right
            res_to_draw = pm_cutout or pm_checker
            if res_to_draw and right_width > 0:
                painter.save()
                painter.setClipRect(QRectF(split_x, target_rect.y(), right_width, target_rect.height()))
                painter.drawPixmap(target_rect.toRect(), res_to_draw)
                painter.restore()

            # draw divider line
            painter.setPen(QPen(QColor(230, 235, 245), 2))
            painter.drawLine(QPointF(split_x, target_rect.y()), QPointF(split_x, target_rect.y() + target_rect.height()))

            # divider handle indicator
            center_y = target_rect.y() + target_rect.height() / 2
            painter.setBrush(QBrush(QColor(230, 235, 245)))
            painter.setPen(QPen(QColor(36, 40, 46), 1))
            painter.drawEllipse(QPointF(split_x, center_y), 4, 4)
        else:
            if pm_cutout:
                self._draw_checkerboard(painter, target_rect)
                painter.drawPixmap(target_rect.toRect(), pm_cutout)
            elif pm_orig:
                painter.drawPixmap(target_rect.toRect(), pm_orig)

        # draw subtle zoom badge only when zoomed in/out
        if self._zoom_mode != "fit" or abs(self._zoom_scale - 1.0) > 1e-3:
            zoom_text = f"{int(self._zoom_scale * 100)}%"
            painter.setPen(QColor(140, 148, 160))
            painter.drawText(QRectF(10, h - 22, 60, 16), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, zoom_text)
