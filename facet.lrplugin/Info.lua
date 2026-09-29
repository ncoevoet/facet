return {
    LrSdkVersion = 15.0,
    LrSdkMinimumVersion = 6.0,

    LrToolkitIdentifier = 'com.facet.lightroom',
    LrPluginName = 'Facet',
    LrPluginInfoUrl = 'https://github.com/ncoevoet/facet',

    LrLibraryMenuItems = {
        {
            title = 'Facet: Apply ratings and flags...',
            file = 'FacetApply.lua',
        },
        {
            title = 'Facet: Export Lightroom State to Facet...',
            file = 'FacetExportState.lua',
        },
    },

    LrMetadataProvider = 'FacetMetadata.lua',

    VERSION = { major = 1, minor = 0, revision = 0, build = 0 },
}
