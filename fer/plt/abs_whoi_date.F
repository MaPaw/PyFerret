	CHARACTER*14 FUNCTION ABS_WHOI_DATE( secsfrombc, cal_id )

*
*
*  This software was developed by the Thermal Modeling and Analysis
*  Project(TMAP) of the National Oceanographic and Atmospheric
*  Administration's (NOAA) Pacific Marine Environmental Lab(PMEL),
*  hereafter referred to as NOAA/PMEL/TMAP.
*
*  Access and use of this software shall impose the following
*  obligations and understandings on the user. The user is granted the
*  right, without any fee or cost, to use, copy, modify, alter, enhance
*  and distribute this software, and any derivative works thereof, and
*  its supporting documentation for any purpose whatsoever, provided
*  that this entire notice appears in all copies of the software,
*  derivative works and supporting documentation.  Further, the user
*  agrees to credit NOAA/PMEL/TMAP in any publications that result from
*  the use of this software or in any product that includes this
*  software. The names TMAP, NOAA and/or PMEL, however, may not be used
*  in any advertising or publicity to endorse or promote any products
*  or commercial entity unless specific written permission is obtained
*  from NOAA/PMEL/TMAP. The user also understands that NOAA/PMEL/TMAP
*  is not obligated to provide the user with any support, consulting,
*  training or assistance of any kind with regard to the use, operation
*  and performance of this software nor to provide the user with any
*  updates, revisions, new versions or "bug fixes".
*
*  THIS SOFTWARE IS PROVIDED BY NOAA/PMEL/TMAP "AS IS" AND ANY EXPRESS
*  OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
*  WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
*  ARE DISCLAIMED. IN NO EVENT SHALL NOAA/PMEL/TMAP BE LIABLE FOR ANY SPECIAL,
*  INDIRECT OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES WHATSOEVER
*  RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER IN AN ACTION OF
*  CONTRACT, NEGLIGENCE OR OTHER TORTUOUS ACTION, ARISING OUT OF OR IN
*  CONNECTION WITH THE ACCESS, USE OR PERFORMANCE OF THIS SOFTWARE. 
*
*
* create a string of the form YYMMDDHHMM from the absolute time in seconds

* programmer - steve hankin
* NOAA/PMEL, Seattle, WA - Tropical Modeling and Analysis Program

* V300: 10/93 *sh*  most of the code lifted from WHOI_DATE
* V420: 11/27/95 - 4-digit YEARS!!
* v530: 1/01  *acm*  calendar ID passed in for alternative calendar types
*       *acm* 3/12 cleanup ifdefs and unnecessary include files

	include 'tmap_dims.parm'
	include 'xtm_grid.cmn_text'
	external xgt_grid_data
	include 'ferret.parm'

* calling argument declarations
	REAL*8	secsfrombc

* internal variable declarations
	INTEGER 	yr100, yr, mon, day, hr, min, sec,
     .			status, i, axis, grid
	INTEGER		cal_id
	CHARACTER*20	TM_SECS_TO_DATE, date

* Convert to date string
	date = TM_SECS_TO_DATE(secsfrombc, cal_id)

* break the date string into component integer values
	CALL TM_BREAK_DATE( date, cal_id, yr, mon, day, hr, min, 
     .                      sec, status )
	yr100 = yr/100		! 1980 --> 19
	yr = yr - (yr100*100)	! 1982 --> 82

* assemble the pieces in WHOI format
	WRITE (ABS_WHOI_DATE,3000) yr100,yr,mon,day,hr,min,sec
 3000	FORMAT (7I2.2)

	RETURN
	END
