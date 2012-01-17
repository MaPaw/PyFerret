#ifndef PYQTCAIRO_CFERBIND_H_
#define PYQTCAIRO_CFERBIND_H_

/* Make sure Python.h is always included first */
#include <Python.h>
#include "grdel.h"
#include "cferbind.h"

grdelBool pyqtcairoCFerBind_setImageName(CFerBind *self, const char *imagename,
                            int imgnamelen, const char *formatname, int fmtnamelen);
grdelBool pyqtcairoCFerBind_deleteWindow(CFerBind *self);
grdelBool pyqtcairoCFerBind_updateWindow(CFerBind *self);
grdelBool pyqtcairoCFerBind_clearWindow(CFerBind *self, grdelType fillcolor);
double *  pyqtcairoCFerBind_windowDpi(CFerBind *self);
grdelBool pyqtcairoCFerBind_resizeWindow(CFerBind *self, double width, double height);
grdelBool pyqtcairoCFerBind_showWindow(CFerBind *self, int visible);
grdelBool pyqtcairoCFerBind_saveWindow(CFerBind *self, const char *filename, int namelen,
                                       const char *formatname, int fmtnamelen, int transbkg);

#endif