#include <stdint.h>
#include <stdlib.h>
#include <libxml/parser.h>
#include <libxml/tree.h>

extern "C" int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size)
{
    xmlDocPtr doc;
    xmlInitParser();
    doc = xmlReadMemory((const char *)data, size, "noname.xml", NULL, 0);
    if (doc != NULL)
        xmlFreeDoc(doc);
    xmlCleanupParser();
    return 0;
}
