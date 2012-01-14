/* Python.h should always be first */
#include <Python.h>
#include <string.h>
#include "grdel.h"
#include "cferbind.h"
#include "cairoCFerBind.h"
#include "pyqtcairoCFerBind.h"

/*
 * Saves the current image to file.  Note that the viewer
 * may have scaled the image.  If so, the scaled image is
 * what will be saved to file.
 *
 * Arguments:
 *     filename   - name of the image file to create, or an
 *                  empty string or NULL
 *     namelen    - actual length of filename (zero if NULL)
 *     formatname - name of the image format (case insensitive)
 *                  only raster image formats are supported
 *     fmtnamelen - actual length of format (zero if NULL)
 *     transbkg   - leave the background transparent?
 *
 * If filename is empty or NULL, the imagename argument for the
 * last call to pyqtcairoCFerBind_setImageName is used for the
 * filename.
 *
 * If format is empty or NULL, the image format is determined
 * from the extension of the filename.  In this case it is
 * an error if the extension does not exist or is not recognized.
 *
 * If transbkg is non-zero, the image background will be
 * transparent (if the format supports the alpha channel;
 * otherwise it will be black).  If transbkg is zero, the
 * image background will be the last clearing color specified.
 *
 * Returns one if successful.   If an error occurs, grdelerrmsg
 * is assigned an appropriate error message and zero is returned.
 */
grdelBool pyqtcairoCFerBind_saveWindow(CFerBind *self, const char *filename,
                            int namelen, const char *formatname,
                            int fmtnamelen, int transbkg)
{
    CairoCFerBindData *instdata;
    grdelBool success;

    /* Sanity checks */
    if ( self->enginename != PyQtCairoCFerBindName ) {
        strcpy(grdelerrmsg, "pyqtcairoCFerBind_saveWindow: unexpected error, "
                            "self is not a valid CFerBind struct");
        return 0;
    }
    instdata = (CairoCFerBindData *) self->instancedata;

    /* Tell the viewer to save the (possibly scaled) image */
    success = grdelWindowSave(instdata->viewer, filename, namelen,
                              formatname, fmtnamelen, transbkg);
    if ( ! success ) {
        /* grdelerrmsg is already assigned */
        return 0;
    }

    return 1;
}

