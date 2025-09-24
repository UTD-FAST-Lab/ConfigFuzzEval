#include <stdint.h>
#include <stddef.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h> // mkstemp, write, close, unlink
#include <fcntl.h>  // file control
#include "tiffio.h"

extern "C" int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size)
{
    if (size < 4)
        return 0;

    // Write fuzz input to tmp file
    char filename[] = "/tmp/inputXXXXXX";
    int fd = mkstemp(filename);
    if (fd < 0)
        return 0;

    ssize_t written = write(fd, data, size);
    (void)written; // silence unused warning
    close(fd);

    TIFF *tiff = TIFFOpen(filename, "r");
    if (tiff)
    {
        uint32_t w, h;
        if (TIFFGetField(tiff, TIFFTAG_IMAGEWIDTH, &w) &&
            TIFFGetField(tiff, TIFFTAG_IMAGELENGTH, &h))
        {
            uint32_t *raster = (uint32_t *)_TIFFmalloc(w * h * sizeof(uint32_t));
            if (raster)
            {
                TIFFReadRGBAImage(tiff, w, h, raster, 0);
                _TIFFfree(raster);
            }
        }
        TIFFClose(tiff);
    }

    unlink(filename);
    return 0;
}
