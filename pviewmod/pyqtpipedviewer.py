'''
PyQtPipedViewer is a graphics viewer application written in PyQt4
that receives its drawing and other commands primarily from another
application through a pipe.  A limited number of commands are
provided by the viewer itself to allow saving and some manipulation
of the displayed image.  The controlling application, however, may
be unaware of these modifications made to the image.

PyQtPipedEditorProcess is used to create and run a PyQtPipedViewer.

This package was developed by the Thermal Modeling and Analysis
Project (TMAP) of the National Oceanographic and Atmospheric
Administration's (NOAA) Pacific Marine Environmental Lab (PMEL).
'''

import sip
try:
    sip.setapi('QVariant', 2)
except AttributeError:
    pass

from PyQt4.QtCore import Qt, QPointF, QRect, QRectF, QSize, QString, QTimer
from PyQt4.QtGui  import QAction, QApplication, QBrush, QColor, \
                         QDialog, QFileDialog, QImage, QLabel, \
                         QMainWindow, QMessageBox, QPainter, QPalette, \
                         QPen, QPicture, QPixmap, QPolygonF, QPrintDialog, \
                         QPrinter, QPushButton, QScrollArea

try:
    from PyQt4.QtGui import QTransform
    HAS_QTransform = True
except ImportError:
    from PyQt4.QtGui import QMatrix
    HAS_QTransform = False

try:
    from PyQt4.QtSvg  import QSvgGenerator
    HAS_QSvgGenerator = True
except ImportError:
    HAS_QSvgGenerator = False

from pyqtcmndhelper import PyQtCmndHelper
from pyqtscaledialog import PyQtScaleDialog
from multiprocessing import Pipe, Process
import sys
import time
import os


class PyQtPipedViewer(QMainWindow):
    '''
    A PyQt graphics viewer that receives generic drawing commands
    through a pipe.  Uses a QPixmap in a QLabel to display the
    image and a list of QPictures to record the drawings.

    A drawing command is a dictionary with string keys that will be
    interpreted into the appropriate PyQt command(s).  For example,
        { "action":"drawText",
          "text":"Hello",
          "font":{"family":"Times", "size":100, "italic":True},
          "fill":{"color":0x880000, "style":"cross"},
          "outline":{"color":"black"},
          "location":(250,350) }

    The command { "action":"exit" } will shutdown the viewer and is
    the only way the viewer can be closed.  GUI actions can only hide
    the viewer.
    '''

    def __init__(self, cmndpipe, rspdpipe):
        '''
        Create a PyQt viewer which reads commands from the Pipe
        cmndpipe and writes responses back to rspdpipe.
        '''
        super(PyQtPipedViewer, self).__init__()
        self.__cmndpipe = cmndpipe
        self.__rspdpipe = rspdpipe
        # QPicture/QPainter pair for the current view
        self.__activepicture = None
        self.__activepainter = None
        # data for recreating the current view
        self.__fracsides = None
        self.__usersides = None
        self.__clipit = True
        # number of drawing commands in the active painter
        self.__drawcount = 0
        # Limit the number of drawing commands per picture
        # when visible to avoid the appearance of being "stuck"
        self.__max_draws_per_picture = 256
        # maximum user Y coordinate - used by adjustPoint
        self.__userymax = 1.0
        # scaling and and pictures for creating the scene
        self.__scalefactor = 1.0
        self.__viewpics = [ ]
        # values used to decide if the label needs to be updated 
        self.__lastpicdrawn = 0
        self.__createpixmap = True
        self.__clearpixmap = True
        # initialize default color for clearScene to transparent white
        self.__lastclearcolor = QColor(0xFFFFFF)
        self.__lastclearcolor.setAlpha(0)
        # create the label, that will serve as the canvas, in a scrolled area
        self.__scrollarea = QScrollArea(self)
        self.__label = QLabel(self.__scrollarea)
        # set the default label size = sqrt(0.75) * (1280, 1024)
        # and set other label values for the scrolled area
        self.__labelwidth = 1110
        self.__labelheight = 890
        self.__label.setMinimumSize(self.__labelwidth, self.__labelheight)
        self.__label.resize(self.__labelwidth, self.__labelheight)
        # setup the scrolled area
        self.__scrollarea.setWidget(self.__label)
        self.__scrollarea.setBackgroundRole(QPalette.Dark)
        self.setCentralWidget(self.__scrollarea)
        self.__minsize = 256
        # command helper object
        self.__helper = PyQtCmndHelper(self)
        # Create the menubar
        self.createActions()
        self.createMenus()
        self.__lastfilename = ""
        self.__shuttingdown = False
        # Put in a default message in the statusbar
        self.statusBar().showMessage("Ready")
        # Set the initial size of the viewer
        mwwidth = self.__labelwidth + 8
        mwheight = self.__labelheight + 8 + self.menuBar().height() + self.statusBar().height()
        self.resize(mwwidth, mwheight)
        # check the command queue any time there are no window events to deal with
        self.__timer = QTimer(self)
        self.__timer.timeout.connect(self.checkCommandPipe)
        self.__timer.setInterval(0)
        self.__timer.start()

    def createActions(self):
        '''
        Create the actions used by the menus in this viewer.  Ownership
        of the actions are not transferred in addAction, thus the need
        to maintain references here.
        '''
        self.__saveact = QAction(self.tr("&Save"), self,
                                shortcut=self.tr("Ctrl+S"),
                                statusTip=self.tr("Save the scene to file"),
                                triggered=self.inquireSaveFilename)
        self.__scaleact = QAction(self.tr("Sc&ale"), self,
                                shortcut=self.tr("Ctrl+A"),
                                statusTip=self.tr("Scale the scene (canvas and drawn images change)"),
                                triggered=self.inquireSceneScale)
        self.__updateact = QAction(self.tr("&Update"), self,
                                shortcut=self.tr("Ctrl+U"),
                                statusTip=self.tr("Update the scene to the current content"),
                                triggered=self.updateScene)
        self.__redrawact = QAction(self.tr("&Redraw"), self,
                                shortcut=self.tr("Ctrl+R"),
                                statusTip=self.tr("Clear and redraw the scene to the current content"),
                                triggered=self.redrawScene)
        self.__hideact = QAction(self.tr("&Hide"), self,
                                shortcut=self.tr("Ctrl+H"),
                                statusTip=self.tr("Hide the viewer"),
                                triggered=self.hide)
        self.__aboutact = QAction(self.tr("&About"), self,
                                statusTip=self.tr("Show information about this viewer"),
                                triggered=self.aboutMsg)
        self.__aboutqtact = QAction(self.tr("About &Qt"), self,
                                statusTip=self.tr("Show information about the Qt library"),
                                triggered=self.aboutQtMsg)
        self.__exitact = QAction(self.tr("E&xit"), self,
                                statusTip=self.tr("Shut down the viewer"),
                                triggered=self.exitViewer)

    def createMenus(self):
        '''
        Create the menu items for the viewer
        using the previously created actions.
        '''
        menuBar = self.menuBar()
        sceneMenu = menuBar.addMenu(menuBar.tr("&Scene"))
        sceneMenu.addAction(self.__saveact)
        sceneMenu.addAction(self.__scaleact)
        sceneMenu.addAction(self.__updateact)
        sceneMenu.addAction(self.__redrawact)
        sceneMenu.addSeparator()
        sceneMenu.addAction(self.__hideact)
        helpMenu = menuBar.addMenu(menuBar.tr("&Help"))
        helpMenu.addAction(self.__aboutact)
        helpMenu.addAction(self.__aboutqtact)
        helpMenu.addSeparator()
        helpMenu.addAction(self.__exitact)

    def showEvent(self, event):
        '''
        When the viewer is going to be shown, make sure all
        the current pictures are displayed in the scene.
        '''
        # update, ignoring the visibility flags
        self.drawLastPictures(True)
        event.accept()

    def closeEvent(self, event):
        '''
        Override so the viewer cannot be closed from the
        user selecting the windowframe close ('X') button.
        Instead only hide the window.
        '''
        if self.__shuttingdown:
            event.accept()
        else:
            event.ignore()
            self.hide()

    def exitViewer(self):
        '''
        Close and exit the viewer.
        '''
        self.__timer.stop()
        self.__shuttingdown = True
        self.close()

    def aboutMsg(self):
        QMessageBox.about(self, self.tr("About PyQtPipedViewer"),
            self.tr("\n" \
            "PyQtPipedViewer is a graphics viewer application that " \
            "receives its drawing and other commands primarily from " \
            "another application through a pipe.  A limited number " \
            "of commands are provided by the viewer itself to allow " \
            "saving and some manipulation of the displayed scene.  " \
            "The controlling application, however, will be unaware " \
            "of these modifications made to the scene. " \
            "\n\n" \
            "Normally, the controlling program will exit the viewer " \
            "when it is no longer needed.  The Help -> Exit menu item " \
            "should not normally be used.  It is provided when problems " \
            "occur and the controlling program cannot shut down the " \
            "viewer properly. " \
            "\n\n" \
            "PyQtViewer was developed by the Thermal Modeling and Analysis " \
            "Project (TMAP) of the National Oceanographic and Atmospheric " \
            "Administration's (NOAA) Pacific Marine Environmental Lab (PMEL). "))

    def aboutQtMsg(self):
        QMessageBox.aboutQt(self, self.tr("About Qt"))

    def paintScene(self, painter, first, leftx, uppery, scalefactor, statusmsg):
        '''
        Draws the pictures self.__viewpics[first:] using the QPainter
        painter.  This QPainter should have been initialized
        appropriately for the QPaintDevice to which it is painting
        (e.g., QImage.fill with the desired background color).

        The point (leftx, uppery) is the offset of the origin prior to
        scaling using scalefactor.  (All are floating point values.)

        The status bar will be updated with a message derived from
        statusmsg before drawing each picture.  Upon completion, the
        status bar will be reset to the "Ready" message.

        The call to painter.end() will need to be made after calling
        this function.
        '''
        # get the origin for drawing the pictures after scaling
        myorigin = QPointF(leftx / scalefactor, uppery / scalefactor)
        # apply the scaling factor in both dimensions
        painter.scale(scalefactor, scalefactor)
        # create the incomplete status message
        mymsg = self.tr("%s (piece %%1 of %%2)" % statusmsg)
        endstr = str(len(self.__viewpics))
        # draw the appropriate pictures
        k = first
        for viewpic in self.__viewpics[first:]:
            k += 1
            # show the progress message
            self.statusBar().showMessage( mymsg.arg(str(k)).arg(endstr) )
            # draw the picture
            painter.drawPicture(myorigin, viewpic)
        # done - clear the status message
        self.statusBar().showMessage( self.tr("Ready") )

    def drawLastPictures(self, ignorevis):
        '''
        Update the scene with pictures yet to be drawn.
        If ignorevis is True, the update will be done
        even if the viewer is not visible; otherwise
        drawing to the scene label is only done if the
        viewer is visible.
        '''
        if not ignorevis:
            if self.isHidden() or self.isMinimized():
                # Not shown, so do not waste time drawing
                return
        if self.__createpixmap:
            # Create and assign a cleared pixmap
            mypixmap = QPixmap(self.__label.size())
            mypixmap.fill(self.__lastclearcolor)
            self.__label.setPixmap(mypixmap)
            self.__createpixmap = False
            self.__clearpixmap = False
        elif self.__clearpixmap:
            # Clear the existing pixmap
            self.__label.pixmap().fill(self.__lastclearcolor)
            self.__clearpixmap = False
        elif len(self.__viewpics) <= self.__lastpicdrawn:
            # Nothing changed so just return
            return
        # Only create the QPainter if there are pictures
        # to draw (this is more than just a clear)
        if len(self.__viewpics) > self.__lastpicdrawn:
            painter = QPainter(self.__label.pixmap())
            self.paintScene(painter, self.__lastpicdrawn, \
                            0.0, 0.0, self.__scalefactor, "Drawing")
            painter.end()
        self.__lastpicdrawn = len(self.__viewpics)
        # make sure the label known to redraw
        self.__label.update()

    def clearScene(self, colorinfo):
        '''
        Removes all view pictures, and fills the scene with the color
        described in the colorinfo dictionary.  If colorinfo is None,
        or if no color or an invalid color is specified in this
        dictionary, the color used is the one used from the last
        clearScene call (or transparent white if a color has never
        been specified).
        '''
        # If there is an active View with content,
        # end it now, but do not update the scene
        if self.__activepainter and (self.__drawcount > 0):
            self.endView(False)
            restartview = True
        else:
            restartview = False
        # get the color to use for clearing (the background color)
        if colorinfo:
            try :
                mycolor = self.__helper.getColorFromCmnd(colorinfo)
                if mycolor.isValid():
                    self.__lastclearcolor = mycolor
            except KeyError:
                pass
        # Delete all the pictures from the list and
        # mark that the pixmap needs to be cleared
        self.__viewpics[:] = [ ]
        self.__clearpixmap = True
        self.__lastpicdrawn = 0
        # Update the scene label if visible
        self.drawLastPictures(False)
        # If there was an non-empty active View, restart it
        if restartview:
            self.beginViewFromSides(self.__fracsides, self.__usersides,
                                    self.__clipit)

    def redrawScene(self):
        '''
        Clear and redraw all the pictures to the displayed scene.
        '''
        # If there is an active View, end it now, but do not update the scene
        if self.__activepainter:
            self.endView(False)
            hadactiveview = True
        else:
            hadactiveview = False
        # mark that the pixmap needs to be cleared
        # and all the pictures redrawn
        self.__clearpixmap = True
        self.__lastpicdrawn = 0
        # Update the scene label if visible
        self.drawLastPictures(False)
        # If there was an active View, restart it in this new system
        if hadactiveview:
            self.beginViewFromSides(self.__fracsides, self.__usersides,
                                    self.__clipit)

    def resizeScene(self, width, height):
        '''
        Resize the scene to the given width and height in units
        of 0.001 inches.
        '''
        newwidth = int(width * 0.001 * self.physicalDpiX() + 0.5)
        if newwidth < self.__minsize:
            newwidth = self.__minsize
        newheight = int(height * 0.001 * self.physicalDpiY() + 0.5)
        if newheight < self.__minsize:
            newheight = self.__minsize
        if (newwidth != self.__labelwidth) or (newheight != self.__labelheight):
            # Resize the label and Set label values
            # so the scrollarea knows of the new size
            self.__labelwidth = newwidth
            self.__labelheight = newheight
            self.__label.setMinimumSize(newwidth, newheight)
            self.__label.resize(newwidth, newheight)
            # mark that the pixmap needs to be recreated
            self.__createpixmap = True
            # Redraw the scene from the beginning
            self.redrawScene()

    def inquireSceneScale(self):
        '''
        Prompt the user for the desired scaling factor for the scene.
        '''
        scaledlg = PyQtScaleDialog(self.tr("Scene Size Scaling"),
                       self.tr("Scaling factor (both horiz. and vert.) for the scene"),
                       self.__scalefactor, self.__labelwidth, self.__labelheight,
                       self.__minsize, self.__minsize, self)
        if scaledlg.exec_():
            (newscale, okay) = scaledlg.getValues()
            if okay:
                self.scaleScene(newscale)

    def scaleScene(self, factor):
        '''
        Scales both the horizontal and vertical directions by factor.
        Scaling factors are not accumulative.  So if the scene was
        already scaled, that scaling is "removed" before this scaling
        factor is applied.
        '''
        newfactor = float(factor)
        factorratio = newfactor / self.__scalefactor
        newwidth = int(factorratio * self.__labelwidth + 0.5)
        newheight = int(factorratio * self.__labelheight + 0.5)
        if (newwidth < self.__minsize) or (newheight < self.__minsize):
            # Set to minimum size
            if self.__labelwidth <= self.__labelheight:
                newfactor = float(self.__minsize) / float(self.__labelwidth)
            else:
                newfactor = float(self.__minsize) / float(self.__labelheight)
            newwidth = int(newfactor * self.__labelwidth + 0.5)
            newheight = int(newfactor * self.__labelheight + 0.5)
        if (newwidth != self.__labelwidth) or (newheight != self.__labelheight):
            # Set the new scaling factor
            self.__scalefactor = newfactor
            # Resize the label and set label values
            # so the scrollarea knows of the new size 
            self.__labelwidth = newwidth
            self.__labelheight = newheight
            self.__label.setMinimumSize(newwidth, newheight)
            self.__label.resize(newwidth, newheight)
            # mark that the pixmap needs to be recreated
            self.__createpixmap = True
            # Redraw the scene from the beginning
            self.redrawScene()

    def inquireSaveFilename(self):
        '''
        Prompt the user for the name of the file into which to save the scene.
        The file format will be determined from the filename extension.
        '''
        formattypes = [ ( "png",
                          self.tr("PNG - Portable Networks Graphics (*.png)") ),
                        ( "jpeg",
                          self.tr("JPEG - Joint Photographic Experts Group (*.jpeg *.jpg *.jpe)") ),
                        ( "tiff",
                          self.tr("TIFF - Tagged Image File Format (*.tiff *.tif)") ),
                        ( "pdf",
                          self.tr("PDF - Portable Document Format (*.pdf)") ),
                        ( "ps",
                          self.tr("PS - PostScript (*.ps)") ),
                        ( "bmp",
                          self.tr("BMP - Windows Bitmap (*.bmp)") ),
                        ( "ppm",
                          self.tr("PPM - Portable Pixmap (*.ppm)") ),
                        ( "xpm",
                          self.tr("XPM - X11 Pixmap (*.xpm)") ),
                        ( "xbm",
                          self.tr("XBM - X11 Bitmap (*.xbm)") ), ]
        if HAS_QSvgGenerator:
            formattypes.insert(5, ( "svg",
                          self.tr("SVG - Scalable Vector Graphics (*.svg)") ) )
        # tr returns QStrings so the following does not work
        # filters = ";;".join( [ t[1] for t in formattypes ] )
        filters = QString(formattypes[0][1])
        for typePair in formattypes[1:]:
            filters.append(";;")
            filters.append(typePair[1])
        (fileName, fileFilter) = QFileDialog.getSaveFileNameAndFilter(self,
                                        self.tr("Save the current scene as "),
                                        self.__lastfilename, filters)
        if fileName:
            for (fmt, fmtQName) in formattypes:
                if fmtQName.compare(fileFilter) == 0:
                    fileFormat = fmt
                    break
            else:
                raise RuntimeError( self.tr("Unexpected file format name '%1'") \
                                        .arg(fileFilter) )
            self.saveSceneToFile(fileName, fileFormat, True, True)
            self.__lastfilename = fileName

    def saveSceneToFile(self, filename, imageformat=None,
                        transparentbkg=True, showPrintDialog=False):
        '''
        Save the current scene to the named file.  If imageformat
        is empty or None, the format is guessed from the filename
        extension.

        If transparentbkg is False, the entire scene is initialized
        to the last clearing color, using a filled rectangle for
        vector images.
        If transparentbkg is True, the alpha channel of the last
        clearing color is set to zero before using it to initialize
        the background color of raster images, and no background
        filled rectangle is drawn in vector images.

        If showPrintDialog is True, the standard printer options
        dialog will be shown for PostScript and PDF formats,
        allowing customizations to the file to be created.
        '''
        if not imageformat:
            # Guess the image format from the filename extension
            # to determine if it is a vector type, and if so,
            # which type. All the raster types use a QImage, which
            # does this guessing of format when saving the image.
            fileext = ( os.path.splitext(filename)[1] ).lower()
            if fileext == '.pdf':
                # needs a PDF QPrinter
                myformat = 'pdf'
            elif fileext == '.ps':
                # needs a PS QPrinter
                myformat = 'ps'
            elif fileext == '.svg':
                myformat = 'svg'
            elif fileext == '.gif':
                # check for gif - needs to be changed to png
                myformat = 'gif'
            else:
                # use a QImage and it figure out the format
                myformat = None
        else:
            myformat = imageformat.lower()

        # the filename may need to be change for gif -> png
        if myformat == 'gif':
            # gif not supported - silently change to png
            myformat = 'png'
            myfilename = os.path.splitext(filename)[0] + ".png"
        else:
            myfilename = filename

        # The RHEL5 distribution of Qt4 does not have a QSvgGenerator
        if (not HAS_QSvgGenerator) and (myformat == 'svg'):
            raise ValueError( self.tr("Your version of Qt does not " \
                                      "support generation of SVG files") )

        if (myformat == 'ps') or (myformat == 'pdf'):
            # Setup the QPrinter that will be used to create the PS or PDF file
            printer = QPrinter(QPrinter.HighResolution)
            printer.setOutputFileName(myfilename)
            # The print format is automatically set from the
            # filename extension; so the following is actually
            # only needed for absent or strange extensions
            if myformat == 'ps':
                printer.setOutputFormat(QPrinter.PostScriptFormat)
            else:
                printer.setOutputFormat(QPrinter.PdfFormat)
            # Print to file in color
            printer.setColorMode(printer.Color)
            # Default paper size (letter)
            try:
                printer.setPaperSize(QPrinter.Letter)
            except AttributeError:
                # setPaperSize introduced in 4.4 and made setPageSize obsolete
                # but RHEL5 Qt4 is 4.2
                printer.setPageSize(QPrinter.Letter)
            # Default orientation
            if ( self.__labelwidth > self.__labelheight ):
                printer.setOrientation(QPrinter.Landscape)
            else:
                printer.setOrientation(QPrinter.Portrait)
            # Since printing to file (and not a printer), use the full page
            # Also, ferret already has incorporated a margin in the drawing
            printer.setFullPage(True)
            # Interactive modifications?
            if showPrintDialog:
                # bring up a dialog to allow the user to tweak the default settings
                printdialog = QPrintDialog(printer, self)
                printdialog.setWindowTitle(
                            self.tr("Save Scene PS/PDF Options (Margins Ignored)"))
                if printdialog.exec_() != QDialog.Accepted:
                    return
            # Determine the scaling factor and offsets for centering and filling the page
            pagerect = printer.pageRect()
            (printleftx, printuppery, printfactor) = \
                self.computeScaleAndOffset(pagerect.width(), pagerect.height(),
                                           printer.resolution())
            # Set up to send the drawing commands to the QPrinter
            painter = QPainter(printer)
            if not transparentbkg:
                # draw a rectangle filling the entire scene
                # with the last clearing color
                painter.save()
                painter.fillRect(QRectF(pagerect), self.__lastclearcolor)
                painter.restore()
            # Draw the scene to the printer
            self.paintScene(painter, 0, printleftx, printuppery, printfactor, "Saving")
            painter.end()
        elif myformat == 'svg':
            # if HAS_QSvgGenerator is False, it should never get here
            generator = QSvgGenerator()
            generator.setFileName(myfilename)
            generator.setSize( QSize(self.__labelwidth, self.__labelheight) )
            generator.setViewBox( QRect(0, 0, self.__labelwidth, self.__labelheight) )
            # paint the scene to this QSvgGenerator
            painter = QPainter(generator)
            if not transparentbkg:
                # draw a rectangle filling the entire scene
                # with the last clearing color
                painter.save()
                painter.fillRect( QRectF(0, 0, self.__labelwidth, self.__labelheight),
                                  self.__lastclearcolor )
                painter.restore()
            self.paintScene(painter, 0, 0.0, 0.0, self.__scalefactor, "Saving")
            painter.end()
        else:
            # ARGB32_Premultiplied is reported significantly faster than ARGB32
            image = QImage( QSize(self.__labelwidth, self.__labelheight),
                            QImage.Format_ARGB32_Premultiplied )
            # Initialize the image
            if transparentbkg:
                # Note that this gives black for formats not supporting the alpha
                # channel (JPEG) whereas ARGB32 with 0x00FFFFFF gives white
                image.fill(0)
            else:
                # Clear the image with self.__lastclearcolor
                self.clearImage(image)
            # paint the scene to this QImage
            painter = QPainter(image)
            self.paintScene(painter, 0, 0.0, 0.0, self.__scalefactor, "Saving")
            painter.end()
            # save the image to file
            image.save(myfilename, myformat)

    def computeScaleAndOffset(self, printwidth, printheight, printresolution):
        '''
        Computes the scaling factor and upper left coordinates required so
        the current scene will be centered and fill the page on described
        by printwidth, printheight, and printresolution.

        Arguments:
            printwidth: width of the print page in pixels
            printheight: height of the print page in pixels
            printresolution: resolution of the print page in DPI

        Returns:
            (leftx, uppery, scalefactor) giving the required
            left offset, top offset, and scaling factor for
            the paintScene method.
        '''
        # get the widths and heights of the printer page and label in inches
        fltprintresolution = float(printresolution)
        fltprintwidth = float(printwidth) / fltprintresolution
        fltprintheight = float(printheight) / fltprintresolution
        fltlabelwidth = float(self.__labelwidth) / float(self.physicalDpiX())
        fltlabelheight = float(self.__labelheight) / float(self.physicalDpiY())
        # Determine the scaling factor for filling the page
        scalefactor = min(fltprintwidth / fltlabelwidth, 
                          fltprintheight / fltlabelheight)
        # Determine the offset to center the picture
        leftx  = 0.5 * fltprintresolution * \
                (fltprintwidth - scalefactor * fltlabelwidth)
        uppery = 0.5 * fltprintresolution * \
                (fltprintheight - scalefactor * fltlabelheight)
        # Account for the current scaling factor in the label size
        scalefactor *= self.__scalefactor
        return (leftx, uppery, scalefactor)

    def clearImage(self, image):
        '''
        Clears the Format_ARGB32_Premultiplied QImage given by image
        with the last clearing color.
        '''
        (redint, greenint, blueint, alphaint) = self.__lastclearcolor.getRgb()
        # Multiply the RGB values by the alpha factor
        alphafactor = alphaint / 255.0
        redint = int( redint * alphafactor + 0.5 )
        if redint > alphaint:
            redint = alphaint
        greenint = int( greenint * alphafactor + 0.5 )
        if greenint > alphaint:
            greenint = alphaint
        blueint = int( blueint * alphafactor + 0.5 )
        if blueint > alphaint:
            blueint = alphaint
        fillint = ((alphaint * 256 + redint) * 256 + greenint) * 256 + blueint
        image.fill(fillint)

    def checkCommandPipe(self):
        '''
        Get and perform commands waiting in the pipe.
        Stop when no more commands or if more than
        100 msec have passed.
        '''
        try:
            starttime = time.clock()
            while self.__cmndpipe.poll():
                cmnd = self.__cmndpipe.recv()
                self.processCommand(cmnd)
                if (time.clock() - starttime) > 0.1:
                    break
        except Exception:
            # EOFError should never arise from recv since
            # the call is after poll returns True
            (exctype, excval) = sys.exc_info()[:2]
            if excval:
                self.__rspdpipe.send("**ERROR %s: %s" % (str(exctype), str(excval)))
            else:
                self.__rspdpipe.send("**ERROR %s" % str(exctype))
            self.exitViewer()

    def processCommand(self, cmnd):
        '''
        Examine the action of cmnd and call the appropriate
        method to deal with this command.  Raises a KeyError
        if the "action" key is missing.
        '''
        cmndact = cmnd["action"]
        if cmndact == "clear":
            self.clearScene(cmnd)
        elif cmndact == "exit":
            self.exitViewer()
        elif cmndact == "hide":
            self.hide()
        elif cmndact == "dpi":
            windowdpi = ( self.physicalDpiX(), self.physicalDpiY() )
            self.__rspdpipe.send(windowdpi)
        elif cmndact == "update":
            self.updateScene()
        elif cmndact == "redraw":
            self.redrawScene()
        elif cmndact == "resize":
            mysize = self.__helper.getSizeFromCmnd(cmnd)
            self.resizeScene(mysize.width(), mysize.height())
        elif cmndact == "save":
            filename = cmnd["filename"]
            fileformat = cmnd.get("fileformat", None)
            transparentbkg = cmnd.get("transparentbkg", False)
            self.saveSceneToFile(filename, fileformat, transparentbkg, False)
        elif cmndact == "setTitle":
            self.setWindowTitle(cmnd["title"])
        elif cmndact == "show":
            self.showNormal()
        elif cmndact == "beginView":
            self.beginView(cmnd)
        elif cmndact == "clipView":
            self.clipView(cmnd)
        elif cmndact == "endView":
            self.endView(True)
        elif cmndact == "drawMultiline":
            self.drawMultiline(cmnd)
        elif cmndact == "drawPoints":
            self.drawPoints(cmnd)
        elif cmndact == "drawPolygon":
            self.drawPolygon(cmnd)
        elif cmndact == "drawRectangle":
            self.drawRectangle(cmnd)
        elif cmndact == "drawMulticolorRectangle":
            self.drawMulticolorRectangle(cmnd)
        elif cmndact == "drawText":
            self.drawSimpleText(cmnd)
        else:
            raise ValueError( self.tr("Unknown command action %1") \
                                  .arg(str(cmndact)) )

    def beginView(self, cmnd):
        '''
        Setup a new viewport and window for drawing on a portion
        (possibly all) of the scene.  Recognized keys from cmnd
        are:
            "viewfracs": a dictionary of sides positions (see
                    PyQtCmndHelper.getSidesFromCmnd) giving the
                    fractions [0.0, 1.0] of the way through the
                    scene for the sides of the new View.
            "usercoords": a dictionary of sides positions (see
                    PyQtCmndHelper.getSidesFromCmnd) giving the
                    user coordinates for the sides of the new View.
            "clip": clip to the new View? (default: True)

        Note that the view fraction values are based on (0,0) being the
        bottom left corner and (1,1) being the top right corner.  Thus,
        left < right and bottom < top.

        Raises a KeyError if either the "viewfracs" or the "usercoords"
        key is not given.
        '''
        # Get the view rectangle in fractions of the full scene
        fracsides = self.__helper.getSidesFromCmnd(cmnd["viewfracs"])
        # Get the user coordinates for this view rectangle
        usersides = self.__helper.getSidesFromCmnd(cmnd["usercoords"])
        # Should graphics be clipped to this view?
        try:
            clipit = cmnd["clip"]
        except KeyError:
            clipit = True
        self.beginViewFromSides(fracsides, usersides, clipit)

    def beginViewFromSides(self, fracsides, usersides, clipit):
        '''
        Setup a new viewport and window for drawing on a portion
        (possibly all) of the scene.  The view in fractions of
        the full scene are given in fracsides.  The user coordinates
        for this view are given in usersides.  Sets the clipping
        rectangle to this view.  If clipit is True, graphics
        will be clipped to this view.
        '''
        # If a view is still active, automatically end it
        if self.__activepainter:
            self.endView(True)
        # Get the location for the new view in terms of pixels.
        # Take into account any scaling of the view
        width = float( self.__labelwidth ) / self.__scalefactor
        height = float( self.__labelheight ) / self.__scalefactor
        leftpixel = fracsides.left() * width
        rightpixel = fracsides.right() * width
        bottompixel = fracsides.bottom() * height
        toppixel = fracsides.top() * height
        # perform the checks after turning into units of pixels
        # to make sure the values are significantly different
        if (0.0 > leftpixel) or (leftpixel >= rightpixel) or (rightpixel > width):
            raise ValueError( self.tr("Invalid left, right view fractions: " \
                                      "left in pixels = %1, right in pixels = %2") \
                                  .arg(str(leftpixel)).arg(str(rightpixel)) )
        if (0.0 > bottompixel) or (bottompixel >= toppixel) or (toppixel > height):
            raise ValueError( self.tr("Invalid bottom, top view fractions: " \
                                      "bottom in pixels = %1, top in pixels = %2") \
                                  .arg(str(bottompixel)).arg(str(toppixel)) )
        # Create the view rectangle in device coordinates
        vrectf = QRectF(leftpixel, height - toppixel,
                       rightpixel - leftpixel, toppixel - bottompixel)
        # Get the user coordinates for this view rectangle
        leftcoord = usersides.left()
        rightcoord = usersides.right()
        bottomcoord = usersides.bottom()
        topcoord = usersides.top()
        if leftcoord >= rightcoord:
            raise ValueError( self.tr("Invalid left, right user coordinates: " \
                                      "left = %1, right = %2") \
                                  .arg(str(leftcoord)).arg(str(rightcoord)) )
        if bottomcoord >= topcoord:
            raise ValueError( self.tr("Invalid bottom, top user coordinates: " \
                                      "bottom = %1, top = %2") \
                                  .arg(str(bottomcoord)).arg(str(topcoord)) )
        # Create the view rectangle in user (world) coordinates
        # adjustPoint will correct for the flipped, zero-based Y coordinate
        wrectf = QRectF(leftcoord, 0.0, rightcoord - leftcoord, topcoord - bottomcoord)
        # Compute the entries in the transformation matrix
        m11 = vrectf.width() / wrectf.width()
        m12 = 0.0
        m21 = 0.0
        m22 = vrectf.height() / wrectf.height()
        dx = vrectf.left() - (m11 * wrectf.left())
        dy = vrectf.top() - (m22 * wrectf.top())
        # Create the new picture and painter, and set the view transformation
        self.__activepicture = QPicture()
        self.__activepainter = QPainter(self.__activepicture)
        self.__activepainter.save()
        # Set the viewport and window just to be safe
        self.__activepainter.setViewport(0, 0, self.__labelwidth, self.__labelheight)
        self.__activepainter.setWindow(0, 0, self.__labelwidth, self.__labelheight)
        # Assign the transformation to take the user coordinates to device coordinates
        if HAS_QTransform:
            wvtrans = QTransform(m11, m12, m21, m22, dx, dy)
            self.__activepainter.setWorldTransform(wvtrans, True)
        else:
            wvtrans = QMatrix(m11, m12, m21, m22, dx, dy)
            self.__activepainter.setWorldMatrix(wvtrans, True)
        self.__activepainter.setWorldMatrixEnabled(True)
        # Set the clip rectangle to that of the view; this also activates clipping
        self.__activepainter.setClipRect(wrectf, Qt.ReplaceClip)
        # Disable clipping if not desired at this time
        if not clipit:
            self.__activepainter.setClipping(False)
        # Note that __activepainter has to end before __activepicture will
        # draw anything.  So no need to add it to __viewpics until then.
        self.__drawcount = 0
        # Save the current view sides and clipit setting for recreating the view.
        # Just save the original objects (assume calling functions do not keep them)
        self.__fracsides = fracsides
        self.__usersides = usersides
        self.__clipit = clipit
        # Pull out the top coordinate since this is used a lot (via adjustPoint)
        self.__userymax = usersides.top()

    def clipView(self, cmnd):
        '''
        If cmnd["clip"] is True, activates clipping to the
        current view rectangle.  If cmnd["clip"] is False,
        disable clipping in this view.

        Raises a KeyError if the "clip" key is not given.
        '''
        if cmnd["clip"]:
            self.__activepainter.setClipping(True)
            self.__clipit = True
        else:
            self.__activepainter.setClipping(False)
            self.__clipit = False

    def endView(self, update):
        '''
        Ends the current view and appends it to the list of pictures
        drawn in the scene.  If update is True, the displayed scene
        is updated.
        '''
        self.__activepainter.restore()
        self.__activepainter.end()
        self.__activepainter = None
        # Only save the active picture if it contains something
        if self.__drawcount > 0:
            self.__viewpics.append(self.__activepicture)
            self.__drawcount = 0
            if update:
                # update the scene
                self.drawLastPictures(False)
        self.__activepicture = None

    def updateScene(self):
        '''
        Updates the displayed graphics to include all drawn elements.
        '''
        # If there is an active picture containing something,
        # end the view, thus adding and display this picture,
        # then restart the view.
        if self.__drawcount > 0:
            self.endView(True)
            self.beginViewFromSides(self.__fracsides, self.__usersides,
                                    self.__clipit)

    def drawMultiline(self, cmnd):
        '''
        Draws a collection of connected line segments.

        Recognized keys from cmnd:
            "points": consecutive endpoints of the connected line
                    segments as a list of (x, y) coordinates
            "pen": dictionary describing the pen used to draw the
                    segments (see PyQtCmndHelper.getPenFromCmnd)

        The coordinates are user coordinates from the bottom left corner.

        Raises:
            KeyError if the "points" or "pen" key is not given
            ValueError if there are fewer than two endpoints given
        '''
        ptcoords = cmnd["points"]
        if len(ptcoords) < 2:
            raise ValueError("fewer that two endpoints given")
        adjpts = [ self.adjustPoint(xypair) for xypair in ptcoords ]
        endpts = QPolygonF( [ QPointF(xypair[0], xypair[1]) \
                                  for xypair in adjpts ] )
        mypen = self.__helper.getPenFromCmnd(cmnd["pen"])
        # save the default state of the painter
        self.__activepainter.save()
        try:
            self.__activepainter.setRenderHint(QPainter.Antialiasing, True)
            self.__activepainter.setPen(mypen)
            self.__activepainter.drawPolyline(endpts)
            self.__drawcount += 1
        finally:
            # return the painter to the default state
            self.__activepainter.restore()
        # Limit the number of drawing commands per picture
        if self.__drawcount >= self.__max_draws_per_picture:
            self.updateScene()

    def drawPoints(self, cmnd):
        '''
        Draws a collection of discrete points using a single symbol
        for each point.

        Recognized keys from cmnd:
            "points": point centers as a list of (x,y) coordinates
            "symbol": name of the symbol to use
                    (see PyQtCmndHelper.getSymbolFromCmnd)
            "size": size of the symbol (scales with view size)
            "color": color name or 24-bit RGB integer value (eg, 0xFF0088)
            "alpha": alpha value from 0 (transparent) to 255 (opaque)

        The coordinates are user coordinates from the bottom left corner.

        Raises a KeyError if the "symbol", "points", or "size" key
        is not given.
        '''
        ptcoords = cmnd["points"]
        ptsize = cmnd["size"]
        sympath = self.__helper.getSymbolFromCmnd(cmnd["symbol"])
        # save the default state of the painter
        self.__activepainter.save()
        try:
            self.__activepainter.setRenderHint(QPainter.Antialiasing, True)
            try:
                mycolor = self.__helper.getColorFromCmnd(cmnd)
                mybrush = QBrush(mycolor, Qt.SolidPattern)
            except KeyError:
                mybrush = QBrush(Qt.SolidPattern)
            if sympath.isFilled():
                self.__activepainter.setBrush(mybrush)
                self.__activepainter.setPen(Qt.NoPen)
            else:
                self.__activepainter.setBrush(Qt.NoBrush)
                mypen = QPen(mybrush, 15.0, Qt.SolidLine,
                             Qt.RoundCap, Qt.RoundJoin)
                self.__activepainter.setPen(mypen)
            scalefactor = ptsize / 100.0
            for xyval in ptcoords:
                (adjx, adjy) = self.adjustPoint( xyval )
                self.__activepainter.save()
                try:
                    self.__activepainter.translate(adjx, adjy)
                    self.__activepainter.scale(scalefactor, scalefactor)
                    self.__activepainter.drawPath(sympath.painterPath())
                finally:
                    self.__activepainter.restore()
            self.__drawcount += len(ptcoords)
        finally:
            # return the painter to the default state
            self.__activepainter.restore()
        # Limit the number of drawing commands per picture
        if self.__drawcount >= self.__max_draws_per_picture:
            self.updateScene()

    def drawPolygon(self, cmnd):
        '''
        Draws a polygon item to the viewer.

        Recognized keys from cmnd:
            "points": the vertices of the polygon as a list of (x,y)
                    coordinates
            "fill": dictionary describing the brush used to fill the
                    polygon; see PyQtCmndHelper.getBrushFromCmnd
                    If not given, the polygon will not be filled.
            "outline": dictionary describing the pen used to outline
                    the polygon; see PyQtCmndHelper.getPenFromCmnd
                    If not given, the polygon border will not be drawn.

        The coordinates are user coordinates from the bottom left corner.

        Raises a KeyError if the "points" key is not given.
        '''
        mypoints = cmnd["points"]
        adjpoints = [ self.adjustPoint(xypair) for xypair in mypoints ]
        mypolygon = QPolygonF( [ QPointF(xypair[0], xypair[1]) \
                                     for xypair in adjpoints ] )
        # save the default state of the painter
        self.__activepainter.save()
        try:
            self.__activepainter.setRenderHint(QPainter.Antialiasing, True)
            try:
                mybrush = self.__helper.getBrushFromCmnd(cmnd["fill"])
            except KeyError:
                mybrush = Qt.NoBrush
            try:
                mypen = self.__helper.getPenFromCmnd(cmnd["outline"])
            except KeyError:
                if ( mybrush == Qt.NoBrush ):
                    raise ValueError( self.tr('drawPolygon called without a Brush or Pen') )
                # Use a cosmetic Pen matching the brush
                mypen = QPen(mybrush, 0.0, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
            self.__activepainter.setBrush(mybrush)
            self.__activepainter.setPen(mypen)
            self.__activepainter.drawPolygon(mypolygon)
            self.__drawcount += 1
        finally:
            # return the painter to the default state
            self.__activepainter.restore()
        # Limit the number of drawing commands per picture
        if self.__drawcount >= self.__max_draws_per_picture:
            self.updateScene()

    def drawRectangle(self, cmnd):
        '''
        Draws a rectangle in the current view using the information
        in the dictionary cmnd.

        Recognized keys from cmnd:
            "left": x-coordinate of left edge of the rectangle
            "bottom": y-coordinate of the bottom edge of the rectangle
            "right": x-coordinate of the right edge of the rectangle
            "top": y-coordinate of the top edge of the rectangle
            "fill": dictionary describing the brush used to fill the
                    rectangle; see PyQtCmndHelper.getBrushFromCmnd
                    If not given, the rectangle will not be filled.
            "outline": dictionary describing the pen used to outline
                    the rectangle; see PyQtCmndHelper.getPenFromCmnd
                    If not given, the rectangle border will not be drawn.

        The coordinates are user coordinates from the bottom left corner.

        Raises a ValueError if the width or height of the rectangle
        is not positive.
        '''
        # get the left, bottom, right, and top values
        # any keys not given get a zero value
        sides = self.__helper.getSidesFromCmnd(cmnd)
        # adjust to actual view coordinates from the top left
        lefttop = self.adjustPoint( (sides.left(), sides.top()) )
        rightbottom = self.adjustPoint( (sides.right(), sides.bottom()) )
        width = rightbottom[0] - lefttop[0]
        if width <= 0.0:
            raise ValueError("width of the rectangle in not positive")
        height = rightbottom[1] - lefttop[1]
        if height <= 0.0:
            raise ValueError("height of the rectangle in not positive")
        myrect = QRectF(lefttop[0], lefttop[1], width, height)
        # save the default state of the painter
        self.__activepainter.save()
        try:
            try:
                mypen = self.__helper.getPenFromCmnd(cmnd["outline"])
                self.__activepainter.setPen(mypen)
            except KeyError:
                self.__activepainter.setPen(Qt.NoPen)
            try:
                mybrush = self.__helper.getBrushFromCmnd(cmnd["fill"])
                self.__activepainter.setBrush(mybrush)
            except KeyError:
                self.__activepainter.setBrush(Qt.NoBrush)
            self.__activepainter.drawRect(myrect)
            self.__drawcount += 1
        finally:
            # return the painter to the default state
            self.__activepainter.restore()
        # Limit the number of drawing commands per picture
        if self.__drawcount >= self.__max_draws_per_picture:
            self.updateScene()

    def drawMulticolorRectangle(self, cmnd):
        '''
        Draws a multi-colored rectangle in the current view using
        the information in the dictionary cmnd.

        Recognized keys from cmnd:
            "left": x-coordinate of left edge of the rectangle
            "bottom": y-coordinate of the bottom edge of the rectangle
            "right": x-coordinate of the right edge of the rectangle
            "top": y-coordinate of the top edge of the rectangle
            "numrows": the number of equally spaced rows
                    to subdivide the rectangle into
            "numcols": the number of equally spaced columns
                    to subdivide the rectangle into
            "colors": iterable representing a flattened column-major
                    2-D array of color dictionaries
                    (see PyQtCmndHelper.getcolorFromCmnd) which are
                    used to create solid brushes to fill each of the
                    cells.  The first row is at the top; the first
                    column is on the left.

        The coordinates are user coordinates from the bottom left corner.

        Raises:
            KeyError: if the "numrows", "numcols", or "colors" keys
                    are not given; if the "color" key is not given
                    in a color dictionary
            ValueError: if the width or height of the rectangle is
                    not positive; if the value of the "numrows" or
                    "numcols" key is not positive; if a color
                    dictionary does not produce a valid color
            IndexError: if not enough colors were given
        '''
        # get the left, bottom, right, and top values
        # any keys not given get a zero value
        sides = self.__helper.getSidesFromCmnd(cmnd)
        # adjust to actual view coordinates from the top left
        lefttop = self.adjustPoint( (sides.left(), sides.top()) )
        rightbottom = self.adjustPoint( (sides.right(), sides.bottom()) )
        width = rightbottom[0] - lefttop[0]
        if width <= 0.0:
            raise ValueError("width of the rectangle in not positive")
        height = rightbottom[1] - lefttop[1]
        if height <= 0.0:
            raise ValueError("height of the rectangle in not positive")
        numrows = int( cmnd["numrows"] + 0.5 )
        if numrows < 1:
            raise ValueError("numrows not a positive integer value")
        numcols = int( cmnd["numcols"] + 0.5 )
        if numcols < 1:
            raise ValueError("numcols not a positive integer value")
        colors = [ self.__helper.getColorFromCmnd(colorinfo) \
                                 for colorinfo in cmnd["colors"] ]
        if len(colors) < (numrows * numcols):
            raise IndexError("not enough colors given")

        # save the default state of the painter
        self.__activepainter.save()
        try:
            self.__activepainter.setPen(Qt.NoPen)
            width = width / float(numcols)
            height = height / float(numrows)
            myrect = QRectF(lefttop[0], lefttop[1], width, height)
            colorindex = 0
            for j in xrange(numcols):
                myrect.moveLeft(lefttop[0] + j * width)
                for k in xrange(numrows):
                    myrect.moveTop(lefttop[1] + k * height)
                    mybrush = QBrush(colors[colorindex], Qt.SolidPattern)
                    colorindex += 1
                    self.__activepainter.setBrush(mybrush)
                    self.__activepainter.drawRect(myrect)
            self.__drawcount += numcols * numrows
        finally:
            # return the painter to the default state
            self.__activepainter.restore()
        # Limit the number of drawing commands per picture
        if self.__drawcount >= self.__max_draws_per_picture:
            self.updateScene()

    def drawSimpleText(self, cmnd):
        '''
        Draws a "simple" text item in the current view.
        Raises a KeyError if the "text" key is not given.

        Recognized keys from cmnd:
            "text": string to displayed
            "font": dictionary describing the font to use;  see
                    PyQtCmndHelper.getFontFromCmnd.  If not given
                    the default font for this viewer is used.
            "fill": dictionary describing the pen used to draw the
                    text; see PyQtCmndHelper.getPenFromCmnd.
                    If not given, the default pen for this viewer
                    is used.
            "rotate": clockwise rotation of the text in degrees
            "location": (x,y) location (user coordinates) in the
                    current view window for the baseline of the
                    start of text.
        '''
        mytext = cmnd["text"]
        try:
            startpt = cmnd["location"]
            (xpos, ypos) = self.adjustPoint(startpt)
        except KeyError:
            # Almost certainly an error, so put it someplace
            # where it will be seen, hopefully as an error.
            winrect = self.__activepainter.window()
            xpos = winrect.width() / 2.0
            ypos = winrect.height() / 2.0
        # save the default state of the painter
        self.__activepainter.save()
        try:
            self.__activepainter.setRenderHint(QPainter.Antialiasing, True)
            # Move the coordinate system so the origin is at the start
            # of the text so that rotation is about this point
            self.__activepainter.translate(xpos, ypos)
            try:
                myfont = self.__helper.getFontFromCmnd(cmnd["font"])
                self.__activepainter.setFont(myfont)
            except KeyError:
                pass
            try:
                rotdeg = cmnd["rotate"]
                self.__activepainter.rotate(rotdeg)
            except KeyError:
                pass
            try:
                mypen = self.__helper.getPenFromCmnd(cmnd["fill"])
                self.__activepainter.setPen(mypen)
            except KeyError:
                pass
            self.__activepainter.drawText(0, 0, mytext)
            self.__drawcount += 1
        finally:
            # return the painter to the default state
            self.__activepainter.restore()
        # Limit the number of drawing commands per picture
        if self.__drawcount >= self.__max_draws_per_picture:
            self.updateScene()

    def adjustPoint(self, xypair):
        '''
        Returns appropriate "view" window (logical) coordinates
        corresponding to the coordinate pair given in xypair
        obtained from a command.
        '''
        (xpos, ypos) = xypair
        ypos = self.__userymax - ypos
        return (xpos, ypos)


class PyQtPipedViewerProcess(Process):
    '''
    A Process specifically tailored for creating a PyQtPipedViewer.
    '''
    def __init__(self, cmndpipe, rspdpipe):
        '''
        Create a Process that will produce a PyQtPipedViewer
        attached to the given Pipes when run.
        '''
        Process.__init__(self)
        self.__cmndpipe = cmndpipe
        self.__rspdpipe = rspdpipe

    def run(self):
        '''
        Create a PyQtPipedViewer that is attached
        to the Pipe of this instance.
        '''
        self.__app = QApplication(["PyQtPipedViewer"])
        self.__viewer = PyQtPipedViewer(self.__cmndpipe, self.__rspdpipe)
        result = self.__app.exec_()
        self.__cmndpipe.close()
        self.__rspdpipe.close()
        SystemExit(result)

#
# The following are for testing this (and the pyqtqcmndhelper) modules
#

class _PyQtCommandSubmitter(QDialog):
    '''
    Testing dialog for controlling the addition of commands to a pipe.
    Used for testing PyQtPipedViewer in the same process as the viewer.
    '''
    def __init__(self, parent, cmndpipe, rspdpipe, cmndlist):
        '''
        Create a QDialog with a single QPushButton for controlling
        the submission of commands from cmndlist to cmndpipe.
        '''
        QDialog.__init__(self, parent)
        self.__cmndlist = cmndlist
        self.__cmndpipe = cmndpipe
        self.__rspdpipe = rspdpipe
        self.__nextcmnd = 0
        self.__button = QPushButton("Submit next command", self)
        self.__button.pressed.connect(self.submitNextCommand)
        self.show()

    def submitNextCommand(self):
        '''
        Submit the next command from the command list to the command pipe,
        or shutdown if there are no more commands to submit.
        '''
        try:
            print "Command: %s" % str(self.__cmndlist[self.__nextcmnd])
            self.__cmndpipe.send(self.__cmndlist[self.__nextcmnd])
            self.__nextcmnd += 1
            while self.__rspdpipe.poll():
                print "Response: %s" % str(self.__rspdpipe.recv())
        except IndexError:
            self.__rspdpipe.close()
            self.__cmndpipe.close()
            self.close()


if __name__ == "__main__":
    # vertices of a pentagon (roughly) centered in a 1000 x 1000 square
    pentagonpts = ( (504.5, 100.0), (100.0, 393.9),
                    (254.5, 869.4), (754.5, 869.4),
                    (909.0, 393.9),  )
    # create the list of commands to submit
    drawcmnds = []
    drawcmnds.append( { "action":"setTitle", "title":"Tester" } )
    drawcmnds.append( { "action":"show" } )
    drawcmnds.append( { "action":"clear", "color":0xFFFFFF} )
    drawcmnds.append( { "action":"dpi"} )
    drawcmnds.append( { "action":"resize",
                        "width":5000,
                        "height":5000 } )
    drawcmnds.append( { "action":"beginView",
                        "viewfracs":{"left":0.0, "bottom":0.5,
                                     "right":0.5, "top":1.0},
                        "usercoords":{"left":0, "bottom":0,
                                      "right":1000, "top":1000},
                        "clip":True } )
    drawcmnds.append( { "action":"drawRectangle",
                        "left": 50, "bottom":50,
                        "right":950, "top":950,
                        "fill":{"color":"black", "alpha":64},
                        "outline":{"color":"blue"} } )
    drawcmnds.append( { "action":"drawPolygon",
                        "points":pentagonpts,
                        "fill":{"color":"lightblue"},
                        "outline":{"color":"black",
                                   "width": 50,
                                   "style":"solid",
                                   "capstyle":"round",
                                   "joinstyle":"round" } } )
    drawcmnds.append( { "action":"drawText",
                        "text":"y=100",
                        "font":{"family":"Times", "size":200},
                        "fill":{"color":0x880000},
                        "location":(100,100) } )
    drawcmnds.append( { "action":"drawText",
                        "text":"y=300",
                        "font":{"family":"Times", "size":200},
                        "fill":{"color":0x880000},
                        "location":(100,300) } )
    drawcmnds.append( { "action":"drawText",
                        "text":"y=500",
                        "font":{"family":"Times", "size":200},
                        "fill":{"color":0x880000},
                        "location":(100,500) } )
    drawcmnds.append( { "action":"drawText",
                        "text":"y=700",
                        "font":{"family":"Times", "size":200},
                        "fill":{"color":0x880000},
                        "location":(100,700) } )
    drawcmnds.append( { "action":"endView" } )
    drawcmnds.append( { "action":"show" } )
    drawcmnds.append( { "action":"beginView",
                        "viewfracs":{"left":0.05, "bottom":0.05,
                                     "right":0.95, "top":0.95},
                        "usercoords":{"left":0, "bottom":0,
                                      "right":1000, "top":1000},
                        "clip":True } )
    drawcmnds.append( { "action":"drawMulticolorRectangle",
                        "left": 50, "bottom":50,
                        "right":950, "top":950,
                        "numrows":2, "numcols":3,
                        "colors":( {"color":0xFF0000, "alpha":128},
                                   {"color":0xAA8800, "alpha":128},
                                   {"color":0x00FF00, "alpha":128},
                                   {"color":0x008888, "alpha":128},
                                   {"color":0x0000FF, "alpha":128},
                                   {"color":0x880088, "alpha":128} ) } )
    drawcmnds.append( { "action":"drawText",
                        "text":"R",
                        "font":{"size":200, "bold": True},
                        "fill":{"color":"black"},
                        "rotate":-45,
                        "location":(200,600) } )
    drawcmnds.append( { "action":"drawText",
                        "text":"Y",
                        "font":{"size":200, "bold": True},
                        "fill":{"color":"black"},
                        "rotate":-45,
                        "location":(200,150) } )
    drawcmnds.append( { "action":"drawText",
                        "text":"G",
                        "font":{"size":200, "bold": True},
                        "fill":{"color":"black"},
                        "rotate":-45,
                        "location":(500,600) } )
    drawcmnds.append( { "action":"drawText",
                        "text":"C",
                        "font":{"size":200, "bold": True},
                        "fill":{"color":"black"},
                        "rotate":-45,
                        "location":(500,150) } )
    drawcmnds.append( { "action":"drawText",
                        "text":"B",
                        "font":{"size":200, "bold": True},
                        "fill":{"color":"black"},
                        "rotate":-45,
                        "location":(800,600) } )
    drawcmnds.append( { "action":"drawText",
                        "text":"M",
                        "font":{"size":200, "bold": True},
                        "fill":{"color":"black"},
                        "rotate":-45,
                        "location":(800,150) } )
    drawcmnds.append( { "action":"endView" } )
    drawcmnds.append( { "action":"show" } )
    drawcmnds.append( { "action":"beginView",
                        "viewfracs":{"left":0.0, "bottom":0.0,
                                     "right":1.0, "top":1.0},
                        "usercoords":{"left":0, "bottom":0,
                                      "right":1000, "top":1000},
                        "clip":True } )
    drawcmnds.append( { "action":"drawPoints",
                        "points":( (100, 100),
                                   (100, 300),
                                   (100, 500),
                                   (100, 700),
                                   (100, 900) ),
                        "symbol":".",
                        "size":50,
                        "color":"black" })
    drawcmnds.append( { "action":"drawPoints",
                        "points":( (200, 100),
                                   (200, 300),
                                   (200, 500),
                                   (200, 700),
                                   (200, 900) ),
                        "symbol":"o",
                        "size":50,
                        "color":"black" })
    drawcmnds.append( { "action":"drawPoints",
                        "points":( (300, 100),
                                   (300, 300),
                                   (300, 500),
                                   (300, 700),
                                   (300, 900) ),
                        "symbol":"+",
                        "size":50,
                        "color":"blue" })
    drawcmnds.append( { "action":"drawPoints",
                        "points":( (400, 100),
                                   (400, 300),
                                   (400, 500),
                                   (400, 700),
                                   (400, 900) ),
                        "symbol":"x",
                        "size":50,
                        "color":"black" })
    drawcmnds.append( { "action":"drawPoints",
                        "points":( (500, 100),
                                   (500, 300),
                                   (500, 500),
                                   (500, 700),
                                   (500, 900) ),
                        "symbol":"*",
                        "size":50,
                        "color":"black" })
    drawcmnds.append( { "action":"drawPoints",
                        "points":( (600, 100),
                                   (600, 300),
                                   (600, 500),
                                   (600, 700),
                                   (600, 900) ),
                        "symbol":"^",
                        "size":50,
                        "color":"blue" })
    drawcmnds.append( { "action":"drawPoints",
                        "points":( (700, 100),
                                   (700, 300),
                                   (700, 500),
                                   (700, 700),
                                   (700, 900) ),
                        "symbol":"#",
                        "size":50,
                        "color":"black" })
    drawcmnds.append( { "action":"drawMultiline",
                        "points":( (600, 100),
                                   (300, 300),
                                   (700, 500),
                                   (500, 700),
                                   (300, 500),
                                   (100, 900) ),
                        "pen": {"color":"white",
                                "width":10,
                                "style":"dash",
                                "capstyle":"round",
                                "joinstyle":"round"} } )
    drawcmnds.append( { "action":"endView" } )
    drawcmnds.append( { "action":"show" } )
    drawcmnds.append( { "action":"exit" } )
    # start PyQt
    app = QApplication(["PyQtPipedViewer"])
    # create a PyQtPipedViewer in this process
    cmndrecvpipe, cmndsendpipe = Pipe(False)
    rspdrecvpipe, rspdsendpipe = Pipe(False)
    viewer = PyQtPipedViewer(cmndrecvpipe, rspdsendpipe)
    # create a command submitter dialog
    tester = _PyQtCommandSubmitter(viewer, cmndsendpipe,
                                   rspdrecvpipe, drawcmnds)
    tester.show()
    # let it all run
    result = app.exec_()
    if result != 0:
        sys.exit(result)
