#!/usr/bin/python3

"""

Try to use netcdf4-python

"""

import numpy as np
import netCDF4
import pyLARDA.helpers as h

import logging
logger = logging.getLogger(__name__)


def get_time_slicer(ts, f, time_interval):
    """get time slicer from the time_interval
    Following options are available

    1. time_interval with [ts_begin, ts_end]
    2. only one timestamp is selected and the found
        right one would be beyond the ts range -> argnearest instead searchsorted
    3. only one is timestamp
    """
    #print('timestamps ', h.ts_to_dt(ts[0]), h.ts_to_dt(ts[-1]))
    # setup slice to load base on time_interval
    #it_b = h.argnearest(ts, h.dt_to_ts(time_interval[0]))
    # select first timestamp right of begin (not left if nearer as above) 
    it_b = np.searchsorted(ts, h.dt_to_ts(time_interval[0]), side='right')
    if len(time_interval) == 2:
        it_e = h.argnearest(ts, h.dt_to_ts(time_interval[1]))
        if it_b == ts.shape[0]: it_b = it_b - 1
        if ts[it_e] < h.dt_to_ts(time_interval[0]) - 3 * np.median(np.diff(ts)) \
                or ts[it_b] < h.dt_to_ts(time_interval[0]):
            # second condition is to ensure that no timestamp before
            # the selected interval is choosen
            # (problem with limrad after change of sampling frequency)
            logger.warning(
                'found last profile of file {}\n at ts[it_e] {} too far from {}'.format(
                    f, h.ts_to_dt(ts[it_e]), time_interval[0]))
            return None

        it_e = it_e + 1 if not it_e == ts.shape[0] - 1 else None
        slicer = [slice(it_b, it_e)]
    elif it_b == ts.shape[0]:
        # only one timestamp is selected
        # and the found right one would be beyond the ts range
        it_b = h.argnearest(ts, h.dt_to_ts(time_interval[0]))
        slicer = [slice(it_b, it_b + 1)]
    else:
        slicer = [slice(it_b, it_b + 1)]
    return slicer


def get_var_attr_from_nc(name, paraminfo, variable):
    direct_def = name.replace("identifier_", "")
    # if both are given (eg through inheritance, choose the
    # direct definition)
    logger.debug("attr name {}".format(name))
    if name in paraminfo and direct_def not in paraminfo:
        attr = variable.getncattr(paraminfo[name])
    else:
        attr = paraminfo[name.replace("identifier_", "")]

    return attr


def reader(paraminfo):
    """build a function for reading in time height data"""

    def retfunc(f, time_interval, *further_intervals):
        """function that converts the netCDF to the larda-data-format
        """
        logger.debug("filename at reader {}".format(f))
        with netCDF4.Dataset(f, 'r') as ncD:

            if 'auto_mask_scale' in paraminfo and paraminfo['auto_mask_scale'] == False:
                ncD.set_auto_mask(False)

            times = ncD.variables[paraminfo['time_variable']][:].astype(np.float64)
            if 'time_millisec_variable' in paraminfo.keys() and \
                    paraminfo['time_millisec_variable'] in ncD.variables:
                subsec = ncD.variables[paraminfo['time_millisec_variable']][:] / 1.0e3
                times += subsec
            if 'time_microsec_variable' in paraminfo.keys() and \
                    paraminfo['time_microsec_variable'] in ncD.variables:
                subsec = ncD.variables[paraminfo['time_microsec_variable']][:] / 1.0e6
                times += subsec
            if 'base_time_variable' in paraminfo.keys() and \
                    paraminfo['base_time_variable'] in ncD.variables:
                basetime = ncD.variables[paraminfo['base_time_variable']][:].astype(np.float64)
                times += basetime

            timeconverter, _ = h.get_converter_array(
                paraminfo['time_conversion'], ncD=ncD)
            if isinstance(times, np.ma.MaskedArray):
                ts = timeconverter(times.data)
            else:
                ts = timeconverter(times)
            #get the time slicer from time_interval
            slicer = get_time_slicer(ts, f, time_interval)
            if slicer == None and paraminfo['ncreader'] != 'pollynet_profile':
                return None

            if paraminfo['ncreader'] == "pollynet_profile":
                slicer = [slice(None)]
            
            if paraminfo['ncreader'] in ['timeheight', 'spec', 'mira_noise', 'pollynet_profile']:
                range_tg = True

                range_interval = further_intervals[0]
                ranges = ncD.variables[paraminfo['range_variable']]
                logger.debug('loader range conversion {}'.format(paraminfo['range_conversion']))
                rangeconverter, _ = h.get_converter_array(
                    paraminfo['range_conversion'],
                    altitude=paraminfo['altitude'])
                ir_b = h.argnearest(rangeconverter(ranges[:]), range_interval[0])
                if len(range_interval) == 2:
                    if not range_interval[1] == 'max':
                        ir_e = h.argnearest(rangeconverter(ranges[:]), range_interval[1])
                        ir_e = ir_e + 1 if not ir_e == ranges.shape[0] - 1 else None
                    else:
                        ir_e = None
                    slicer.append(slice(ir_b, ir_e))
                else:
                    slicer.append(slice(ir_b, ir_b + 1))

            if paraminfo['ncreader'] == 'spec':
                vel_tg = True
                slicer.append(slice(None))
            varconverter, maskconverter = h.get_converter_array(
                paraminfo['var_conversion'])

            var = ncD.variables[paraminfo['variable_name']]
            #print('var dict ',ncD.variables[paraminfo['variable_name']].__dict__)
            #print("time indices ", it_b, it_e)
            data = {}
            if paraminfo['ncreader'] == 'timeheight':
                data['dimlabel'] = ['time', 'range']
            elif paraminfo['ncreader'] == 'time':
                data['dimlabel'] = ['time']
            elif paraminfo['ncreader'] == 'spec':
                data['dimlabel'] = ['time', 'range', 'vel']
            elif paraminfo['ncreader'] == 'mira_noise':
                data['dimlabel'] = ['time', 'range']
            elif paraminfo['ncreader'] == "pollynet_profile":
                data['dimlabel'] = ['time', 'range']


            data["filename"] = f
            data["paraminfo"] = paraminfo
            data['ts'] = ts[tuple(slicer)[0]]

            data['system'] = paraminfo['system']
            data['name'] = paraminfo['paramkey']
            data['colormap'] = paraminfo['colormap']

            # experimental: put history into data container
            if 'identifier_history' in paraminfo and paraminfo['identifier_history'] != 'none':
                data['file_history'] = [ncD.getncattr(paraminfo['identifier_history'])]

            if paraminfo['ncreader'] in ['timeheight', 'spec', 'mira_noise', 'pollynet_profile']:
                if isinstance(times, np.ma.MaskedArray):
                    data['rg'] = rangeconverter(ranges[tuple(slicer)[1]].data)
                else:
                    data['rg'] = rangeconverter(ranges[tuple(slicer)[1]])

                data['rg_unit'] = get_var_attr_from_nc("identifier_rg_unit",
                                                       paraminfo, ranges)
                logger.debug('shapes {} {} {}'.format(ts.shape, ranges.shape, var.shape))
            if paraminfo['ncreader'] == 'spec':
                if 'vel_ext_variable' in paraminfo:
                    # this special field is needed to load limrad spectra
                    vel_ext = ncD.variables[paraminfo['vel_ext_variable'][0]][int(paraminfo['vel_ext_variable'][1])]
                    vel_res = 2 * vel_ext / float(var[:].shape[2])
                    data['vel'] = np.linspace(-vel_ext + (0.5 * vel_res),
                                              +vel_ext - (0.5 * vel_res),
                                              var[:].shape[2])
                else:
                    data['vel'] = ncD.variables[paraminfo['vel_variable']][:]
            logger.debug('shapes {} {}'.format(ts.shape, var.shape))
            data['var_unit'] = get_var_attr_from_nc("identifier_var_unit",
                                                    paraminfo, var)
            data['var_lims'] = [float(e) for e in \
                                get_var_attr_from_nc("identifier_var_lims",
                                                     paraminfo, var)]

            # by default assume dimensions of (time, range, ...)
            # or define a custom order in the param toml file
            if 'dimorder' in paraminfo:
                slicer = [slicer[i] for i in paraminfo['dimorder']]

            if paraminfo['ncreader'] == "pollynet_profile":
                del slicer[0]


            if "identifier_fill_value" in paraminfo.keys() and not "fill_value" in paraminfo.keys():
                fill_value = var.getncattr(paraminfo['identifier_fill_value'])
                mask = (var[tuple(slicer)].data == fill_value)
            elif "fill_value" in paraminfo.keys():
                fill_value = paraminfo['fill_value']
                mask = np.isclose(var[tuple(slicer)].data, fill_value)
            else:
                mask = ~np.isfinite(var[tuple(slicer)].data)

            data['mask'] = maskconverter(mask)

            if paraminfo['ncreader'] == 'mira_noise':
                r_c = ncD.variables[paraminfo['radar_const']][:]
                snr_c = ncD.variables[paraminfo['SNR_corr']][:]
                npw = ncD.variables[paraminfo['noise_pow']][:]
                calibrated_noise = r_c[slicer[0], np.newaxis] * var[tuple(slicer)].data * snr_c[tuple(slicer)].data / \
                                   npw[slicer[0], np.newaxis] * (data['rg'][np.newaxis, :] / 5000.) ** 2
                data['var'] = calibrated_noise
            else:
                data['var'] = varconverter(var[tuple(slicer)].data)

            if paraminfo['ncreader'] == "pollynet_profile":
                data['var'] = data['var'][np.newaxis, :]
                data['mask'] = data['mask'][np.newaxis, :]

            return data

    return retfunc


def auxreader(paraminfo):
    """build a function for reading in time height data"""
    def retfunc(f, time_interval, *further_intervals):
        """function that converts the netCDF to the larda-data-format
        this one is for aux values that don't have a dedicated time domain
        (nevertheless the time is read in, to estimate the coverage of the file)
        """
        logger.debug("filename at reader {}".format(f))
        with netCDF4.Dataset(f, 'r') as ncD:

            times = ncD.variables[paraminfo['time_variable']][:].astype(np.float64)
            if 'time_millisec_variable' in paraminfo.keys() and \
                    paraminfo['time_millisec_variable'] in ncD.variables:
                subsec = ncD.variables[paraminfo['time_millisec_variable']][:] / 1.0e3
                times += subsec
            if 'time_microsec_variable' in paraminfo.keys() and \
                    paraminfo['time_microsec_variable'] in ncD.variables:
                subsec = ncD.variables[paraminfo['time_microsec_variable']][:] / 1.0e6
                times += subsec

            timeconverter, _ = h.get_converter_array(
                paraminfo['time_conversion'], ncD=ncD)
            ts = timeconverter(times.data)

            #get the time slicer from time_interval
            slicer = get_time_slicer(ts, f, time_interval)
            if slicer == None and paraminfo['ncreader'] != 'aux_all_ts':
                return None

            if paraminfo['ncreader'] == "aux_all_ts":
                slicer = [slice(None)]

            varconverter, maskconverter = h.get_converter_array(
                paraminfo['var_conversion'])

            var = ncD.variables[paraminfo['variable_name']]
            #print('var dict ',ncD.variables[paraminfo['variable_name']].__dict__)
            #print("time indices ", it_b, it_e)
            data = {}
            data['dimlabel'] = ['time','aux']

            data["filename"] = f
            data["paraminfo"] = paraminfo
            data['ts'] = ts[0:1]

            data['system'] = paraminfo['system']
            data['name'] = paraminfo['paramkey']
            data['colormap'] = paraminfo['colormap']

            logger.debug('shapes {} {}'.format(ts.shape, var.shape))
            data['var_unit'] = get_var_attr_from_nc("identifier_var_unit",
                                                    paraminfo, var)
            data['var_lims'] = [float(e) for e in \
                                get_var_attr_from_nc("identifier_var_lims",
                                                     paraminfo, var)]

            if "identifier_fill_value" in paraminfo.keys() and not "fill_value" in paraminfo.keys():
                fill_value = var.getncattr(paraminfo['identifier_fill_value'])
                mask = (var[:] == fill_value)
            elif "fill_value" in paraminfo.keys():
                fill_value = paraminfo['fill_value']
                mask = np.isclose(var[:], fill_value)
            else:
                mask = ~np.isfinite(var[:])

            data['var'] = varconverter(var[:])
            data['mask'] = maskconverter(mask)

            return data

    return retfunc


def timeheightreader_rpgfmcw(paraminfo):
    """build a function for reading in time height data
    special function for a special instrument ;)

    the issues are:

    - range variable in different file
    - stacking of single variables

    for now works only with 3 chirps and range variable only in level0
    """
    def retfunc(f, time_interval, range_interval):
        """function that converts the netCDF to the larda-data-format
        """
        logger.debug("filename at reader {}".format(f))
        flvl0 = f.replace("LV1", "LV0")
        with netCDF4.Dataset(flvl0) as ncD:

            no_chirps = ncD.dimensions['Chirp'].size

            ranges_per_chirp = [
                ncD.variables['C{}Range'.format(i + 1)] for i in range(no_chirps)]
            ch1range = ranges_per_chirp[0]

            ranges = np.hstack([rg[:] for rg in ranges_per_chirp])

        with netCDF4.Dataset(f, 'r') as ncD:

            times = ncD.variables[paraminfo['time_variable']][:].astype(np.float64)
            if 'time_millisec_variable' in paraminfo.keys() and \
                    paraminfo['time_millisec_variable'] in ncD.variables:
                subsec = ncD.variables[paraminfo['time_millisec_variable']][:] / 1.0e3
                times += subsec
            if 'time_microsec_variable' in paraminfo.keys() and \
                    paraminfo['time_microsec_variable'] in ncD.variables:
                subsec = ncD.variables[paraminfo['time_microsec_variable']][:] / 1.0e6
                times += subsec
            timeconverter, _ = h.get_converter_array(
                paraminfo['time_conversion'], ncD=ncD)
            ts = timeconverter(times)

            #get the time slicer from time_interval
            slicer = get_time_slicer(ts, f, time_interval)
            if slicer == None:
                return None

            rangeconverter, _ = h.get_converter_array(
                paraminfo['range_conversion'])

            varconverter, _ = h.get_converter_array(
                paraminfo['var_conversion'])

            ir_b = h.argnearest(rangeconverter(ranges[:]), range_interval[0])
            if len(range_interval) == 2:
                if not range_interval[1] == 'max':
                    ir_e = h.argnearest(rangeconverter(ranges[:]), range_interval[1])
                    ir_e = ir_e + 1 if not ir_e == ranges.shape[0] - 1 else None
                else:
                    ir_e = None
                slicer.append(slice(ir_b, ir_e))
            else:
                slicer.append(slice(ir_b, ir_b + 1))

            no_chirps = ncD.dimensions['Chirp'].size

            var_per_chirp = [
                ncD.variables['C{}'.format(i + 1) + paraminfo['variable_name']] for i in range(no_chirps)]
            ch1var = var_per_chirp[0]

            #ch1var = ncD.variables['C1'+paraminfo['variable_name']]
            #ch2var = ncD.variables['C2'+paraminfo['variable_name']]
            #ch3var = ncD.variables['C3'+paraminfo['variable_name']]

            #print('var dict ',ch1var.__dict__)
            #print('shapes ', ts.shape, ch1range.shape, ch1var.shape)
            #print("time indices ", it_b, it_e)
            data = {}
            data['dimlabel'] = ['time', 'range']
            data["filename"] = f
            data["paraminfo"] = paraminfo
            data['ts'] = ts[tuple(slicer)[0]]
            data['rg'] = rangeconverter(ranges[tuple(slicer)[1]])

            data['system'] = paraminfo['system']
            data['name'] = paraminfo['paramkey']
            data['colormap'] = paraminfo['colormap']
            data['rg_unit'] = get_var_attr_from_nc("identifier_rg_unit",
                                                   paraminfo, ch1range)
            data['var_unit'] = get_var_attr_from_nc("identifier_var_unit",
                                                    paraminfo, ch1var)
            data['var_lims'] = [float(e) for e in \
                                get_var_attr_from_nc("identifier_var_lims",
                                                     paraminfo, ch1var)]
            var = np.hstack([v[:] for v in var_per_chirp])
            #var = np.hstack([ch1var[:], ch2var[:], ch3var[:]])

            if "identifier_fill_value" in paraminfo.keys() and not "fill_value" in paraminfo.keys():
                fill_value = var.getncattr(paraminfo['identifier_fill_value'])
                data['mask'] = (var[tuple(slicer)].data == fill_value)
            elif "fill_value" in paraminfo.keys():
                fill_value = paraminfo["fill_value"]
                data['mask'] = np.isclose(var[tuple(slicer)], fill_value)
            else:
                data['mask'] = ~np.isfinite(var[tuple(slicer)].data)
            data['var'] = varconverter(var[tuple(slicer)].data)

            return data

    return retfunc


def specreader_rpgfmcw(paraminfo):
    """build a function for reading in spectral data
    special function for a special instrument ;)

    the issues are:

    - range variable in different file
    - stacking of single variables

    for now works only with 3 chirps and range variable only in level0
    """
    def retfunc(f, time_interval, range_interval):
        """function that converts the netCDF to the larda-data-format
        """
        logger.debug("filename at reader {}".format(f))

        with netCDF4.Dataset(f, 'r') as ncD:

            times = ncD.variables[paraminfo['time_variable']][:].astype(np.float64)
            if 'time_millisec_variable' in paraminfo.keys() and \
                    paraminfo['time_millisec_variable'] in ncD.variables:
                subsec = ncD.variables[paraminfo['time_millisec_variable']][:] / 1.0e3
                times += subsec
            if 'time_microsec_variable' in paraminfo.keys() and \
                    paraminfo['time_microsec_variable'] in ncD.variables:
                subsec = ncD.variables[paraminfo['time_microsec_variable']][:] / 1.0e6
                times += subsec
            timeconverter, _ = h.get_converter_array(
                paraminfo['time_conversion'], ncD=ncD)
            ts = timeconverter(times)

            no_chirps = ncD.dimensions['Chirp'].size

            ranges_per_chirp = [
                ncD.variables['C{}Range'.format(i + 1)] for i in range(no_chirps)]
            ch1range = ranges_per_chirp[0]

            ranges = np.hstack([rg[:] for rg in ranges_per_chirp])

            #get the time slicer from time_interval
            slicer = get_time_slicer(ts, f, time_interval)
            if slicer == None:
                return None

            rangeconverter, _ = h.get_converter_array(
                paraminfo['range_conversion'])

            varconverter, _ = h.get_converter_array(
                paraminfo['var_conversion'])

            ir_b = h.argnearest(rangeconverter(ranges[:]), range_interval[0])
            if len(range_interval) == 2:
                if not range_interval[1] == 'max':
                    ir_e = h.argnearest(rangeconverter(ranges[:]), range_interval[1])
                    ir_e = ir_e + 1 if not ir_e == ranges.shape[0] - 1 else None
                else:
                    ir_e = None
                slicer.append(slice(ir_b, ir_e))
            else:
                slicer.append(slice(ir_b, ir_b + 1))

            vars_per_chirp = [
                ncD.variables['C{}{}'.format(i + 1, paraminfo['variable_name'])] for i in range(no_chirps)]
            ch1var = vars_per_chirp[0]
            #print('var dict ',ch1var.__dict__)
            #print('shapes ', ts.shape, ch1range.shape, ch1var.shape)
            #print("time indices ", it_b, it_e)

            data = {}
            data['dimlabel'] = ['time', 'range', 'vel']
            data["filename"] = f
            data["paraminfo"] = paraminfo
            data['ts'] = ts[tuple(slicer)[0]]
            data['rg'] = rangeconverter(ranges[tuple(slicer)[1]])

            data['system'] = paraminfo['system']
            data['name'] = paraminfo['paramkey']
            data['colormap'] = paraminfo['colormap']
            data['rg_unit'] = get_var_attr_from_nc("identifier_rg_unit",
                                                   paraminfo, ch1range)
            data['var_unit'] = get_var_attr_from_nc("identifier_var_unit",
                                                    paraminfo, ch1var)
            data['var_lims'] = [float(e) for e in \
                                get_var_attr_from_nc("identifier_var_lims",
                                                     paraminfo, ch1var)]
            if 'vel_ext_variable' in paraminfo:
                #define the function
                get_vel_ext = lambda i: ncD.variables[paraminfo['vel_ext_variable'][0]][:][i]
                #apply it to every chirp
                vel_ext_per_chirp = [get_vel_ext(i) for i in range(no_chirps)]

                vel_dim_per_chirp = [v.shape[2] for v in vars_per_chirp]
                calc_vel_res = lambda v_e, v_dim: 2.0 * v_e / float(v_dim)
                vel_res_per_chirp = [calc_vel_res(v_e, v_dim) for v_e, v_dim \
                                     in zip(vel_ext_per_chirp, vel_dim_per_chirp)]

                # for some very obscure reason lambda is not able to unpack 3 values
                def calc_vel(vel_ext, vel_res, v_dim):
                    return np.linspace(-vel_ext + (0.5 * vel_res),
                                       +vel_ext - (0.5 * vel_res),
                                       v_dim)
                vel_per_chirp = [calc_vel(v_e, v_res, v_dim) for v_e, v_res, v_dim \
                                 in zip(vel_ext_per_chirp, vel_res_per_chirp, vel_dim_per_chirp)]
            else:
                raise NotImplemented("other means of getting the var dimension are not implemented yet")
            data['vel'] = vel_per_chirp[0]
            # interpolate the variables here

            vars_interp = [vars_per_chirp[0]] + \
                          [interp_only_3rd_dim(var, vel, vel_per_chirp[0]) \
                           for var, vel in zip(vars_per_chirp[1:], vel_per_chirp[1:])]
            var = np.hstack([v[:] for v in vars_interp])
            logger.debug('interpolated spectra from\n{}\n{} to\n{}'.format(
                [v[:].shape for v in vars_per_chirp],
                ['{:5.3f}'.format(vel[0]) for vel in vel_per_chirp],
                [v[:].shape for v in vars_interp]))
            logger.info('var.shape interpolated spectra {}'.format(var.shape))

            if "identifier_fill_value" in paraminfo.keys() and not "fill_value" in paraminfo.keys():
                fill_value = var.getncattr(paraminfo['identifier_fill_value'])
                data['mask'] = (var[tuple(slicer)].data == fill_value)
            elif "fill_value" in paraminfo.keys():
                fill_value = paraminfo["fill_value"]
                data['mask'] = np.isclose(var[tuple(slicer)], fill_value)
            else:
                data['mask'] = ~np.isfinite(var[tuple(slicer)].data)
            if isinstance(times, np.ma.MaskedArray):
                data['var'] = varconverter(var[tuple(slicer)].data)
            else:
                data['var'] = varconverter(var[tuple(slicer)])

            return data

    return retfunc


def scanreader_mira(paraminfo):
    """reader for the scan files

    - load full file regardless of selected time
    - covers spec_timeheight and spec_time
    """

    def retfunc(f, time_interval, *further_intervals):
        """function that converts the netCDF to the larda-data-format
        """
        logger.debug("filename at reader {}".format(f))
        with netCDF4.Dataset(f, 'r') as ncD:

            times = ncD.variables[paraminfo['time_variable']][:].astype(np.float64)
            if 'time_millisec_variable' in paraminfo.keys() and \
                    paraminfo['time_millisec_variable'] in ncD.variables:
                subsec = ncD.variables[paraminfo['time_millisec_variable']][:] / 1.0e3
                times += subsec
            if 'time_microsec_variable' in paraminfo.keys() and \
                    paraminfo['time_microsec_variable'] in ncD.variables:
                subsec = ncD.variables[paraminfo['time_microsec_variable']][:] / 1.0e6
                times += subsec

            timeconverter, _ = h.get_converter_array(
                paraminfo['time_conversion'], ncD=ncD)
            if isinstance(times, np.ma.MaskedArray):
                ts = timeconverter(times.data)
            else:
                ts = timeconverter(times)

            # load the whole time-range from the file
            slicer = [slice(None)]

            if paraminfo['ncreader'] == 'scan_timeheight':
                range_tg = True

                range_interval = further_intervals[0]
                ranges = ncD.variables[paraminfo['range_variable']]
                logger.debug('loader range conversion {}'.format(paraminfo['range_conversion']))
                rangeconverter, _ = h.get_converter_array(
                    paraminfo['range_conversion'],
                    altitude=paraminfo['altitude'])
                ir_b = h.argnearest(rangeconverter(ranges[:]), range_interval[0])
                if len(range_interval) == 2:
                    if not range_interval[1] == 'max':
                        ir_e = h.argnearest(rangeconverter(ranges[:]), range_interval[1])
                        ir_e = ir_e + 1 if not ir_e == ranges.shape[0] - 1 else None
                    else:
                        ir_e = None
                    slicer.append(slice(ir_b, ir_e))
                else:
                    slicer.append(slice(ir_b, ir_b + 1))

            varconverter, maskconverter = h.get_converter_array(
                paraminfo['var_conversion'],
                mira_azi_zero=paraminfo['mira_azi_zero'])

            var = ncD.variables[paraminfo['variable_name']]
            # print('var dict ',ncD.variables[paraminfo['variable_name']].__dict__)
            # print("time indices ", it_b, it_e)
            data = {}
            if paraminfo['ncreader'] == 'scan_timeheight':
                data['dimlabel'] = ['time', 'range']
            elif paraminfo['ncreader'] == 'scan_time':
                data['dimlabel'] = ['time']
            #elif paraminfo['ncreader'] == 'spec':
            #    data['dimlabel'] = ['time', 'range', 'vel']

            data["filename"] = f
            data["paraminfo"] = paraminfo
            data['ts'] = ts[tuple(slicer)[0]]

            data['system'] = paraminfo['system']
            data['name'] = paraminfo['paramkey']
            data['colormap'] = paraminfo['colormap']

            if paraminfo['ncreader'] == 'scan_timeheight':
                if isinstance(times, np.ma.MaskedArray):
                    data['rg'] = rangeconverter(ranges[tuple(slicer)[1]].data)
                else:
                    data['rg'] = rangeconverter(ranges[tuple(slicer)[1]])

                data['rg_unit'] = get_var_attr_from_nc("identifier_rg_unit",
                                                       paraminfo, ranges)
                logger.debug('shapes {} {} {}'.format(ts.shape, ranges.shape, var.shape))
            logger.debug('shapes {} {}'.format(ts.shape, var.shape))
            data['var_unit'] = get_var_attr_from_nc("identifier_var_unit",
                                                    paraminfo, var)
            data['var_lims'] = [float(e) for e in \
                                get_var_attr_from_nc("identifier_var_lims",
                                                     paraminfo, var)]

            # by default assume dimensions of (time, range, ...)
            # or define a custom order in the param toml file
            if 'dimorder' in paraminfo:
                slicer = [slicer[i] for i in paraminfo['dimorder']]

            if "identifier_fill_value" in paraminfo.keys() and not "fill_value" in paraminfo.keys():
                fill_value = var.getncattr(paraminfo['identifier_fill_value'])
                mask = (var[tuple(slicer)].data == fill_value)
            elif "fill_value" in paraminfo.keys():
                fill_value = paraminfo['fill_value']
                mask = np.isclose(var[tuple(slicer)].data, fill_value)
            else:
                mask = ~np.isfinite(var[tuple(slicer)].data)

            data['var'] = varconverter(var[tuple(slicer)].data)
            data['mask'] = maskconverter(mask)

            return data

    return retfunc


def interp_only_3rd_dim(arr, old, new):
    """function to interpolate only the velocity (3rd) axis"""

    from scipy import interpolate

    f = interpolate.interp1d(old, arr, axis=2,
                             bounds_error=False, fill_value=-999.)
    new_arr = f(new)

    return new_arr


def specreader_kazr(paraminfo):
    """build a function for reading in spectral data
    another special function for another special instrument ;)

    the issues are:

    - variables time and range are merged and can be accessed by a locator mask
    - noise is not saved and has to be computed from the spectra

    """

    def retfunc(f, time_interval, range_interval):
        """function that converts the netCDF to the larda-data-format
        """
        logger.debug("filename at reader {}".format(f))

        with netCDF4.Dataset(f, 'r') as ncD:
            ranges = ncD.variables[paraminfo['range_variable']]
            times = ncD.variables[paraminfo['time_variable']][:].astype(np.float64)
            locator_mask = ncD.variables[paraminfo['mask_var']]
            if 'time_millisec_variable' in paraminfo.keys() and \
                    paraminfo['time_millisec_variable'] in ncD.variables:
                subsec = ncD.variables[paraminfo['time_millisec_variable']][:] / 1.0e3
                times += subsec
            if 'time_microsec_variable' in paraminfo.keys() and \
                    paraminfo['time_microsec_variable'] in ncD.variables:
                subsec = ncD.variables[paraminfo['time_microsec_variable']][:] / 1.0e6
                times += subsec
            if 'basetime' in paraminfo.keys() and \
                    paraminfo['basetime'] in ncD.variables:
                basetime = ncD.variables[paraminfo['basetime']][:].astype(np.float64)
                times += basetime
            timeconverter, _ = h.get_converter_array(
                paraminfo['time_conversion'], ncD=ncD)
            ts = timeconverter(times)

            it_b = np.searchsorted(ts, h.dt_to_ts(time_interval[0]), side='right')
            if len(time_interval) == 2:
                it_e = h.argnearest(ts, h.dt_to_ts(time_interval[1]))
                if it_b == ts.shape[0]: it_b = it_b - 1
                if ts[it_e] < h.dt_to_ts(time_interval[0]) - 3 * np.median(np.diff(ts)) \
                        or ts[it_b] < h.dt_to_ts(time_interval[0]):
                    # second condition is to ensure that no timestamp before
                    # the selected interval is choosen
                    # (problem with limrad after change of sampling frequency)
                    logger.warning(
                        'last profile of file {}\n at {} too far from {}'.format(
                            f, h.ts_to_dt(ts[it_e]), time_interval[0]))
                    return None
                it_e = it_e + 1 if not it_e == ts.shape[0] - 1 else None
                slicer = [slice(it_b, it_e)]
            elif it_b == ts.shape[0]:
                # only one timestamp is selected
                # and the found right one would be beyond the ts range
                it_b = h.argnearest(ts, h.dt_to_ts(time_interval[0]))
                slicer = [slice(it_b, it_b + 1)]
            else:
                slicer = [slice(it_b, it_b + 1)]

            rangeconverter, _ = h.get_converter_array(
                paraminfo['range_conversion'])

            varconverter, _ = h.get_converter_array(
                paraminfo['var_conversion'])

            ir_b = h.argnearest(rangeconverter(ranges[:]), range_interval[0])
            if len(range_interval) == 2:
                if not range_interval[1] == 'max':
                    ir_e = h.argnearest(rangeconverter(ranges[:]), range_interval[1])
                    ir_e = ir_e + 1 if not ir_e == ranges.shape[0] - 1 else None
                else:
                    ir_e = None
                slicer.append(slice(ir_b, ir_e))
            else:
                slicer.append(slice(ir_b, ir_b + 1))

            var = ncD.variables[paraminfo['variable_name']]
            vel = ncD.variables[paraminfo['vel_variable']][:].astype(np.float64)
            # print('var dict ',ch1var.__dict__)
            # print('shapes ', ts.shape, ch1range.shape, ch1var.shape)
            # print("time indices ", it_b, it_e)

            data = {}
            data['var'] = var
            data['dimlabel'] = ['time', 'range', 'vel']
            data["filename"] = f
            data["paraminfo"] = paraminfo
            data['ts'] = ts[tuple(slicer)[0]]
            data['rg'] = rangeconverter(ranges[tuple(slicer)[1]])

            data['system'] = paraminfo['system']
            data['name'] = paraminfo['paramkey']
            data['colormap'] = paraminfo['colormap']
            data['rg_unit'] = get_var_attr_from_nc("identifier_rg_unit",
                                                   paraminfo, ranges)
            data['var_unit'] = get_var_attr_from_nc("identifier_var_unit",
                                                    paraminfo, var)
            data['var_lims'] = [float(e) for e in \
                                get_var_attr_from_nc("identifier_var_lims",
                                                     paraminfo, var)]
            data['vel'] = vel

            if "identifier_fill_value" in paraminfo.keys() and not "fill_value" in paraminfo.keys():
                fill_value = var.getncattr(paraminfo['identifier_fill_value'])
                data['mask'] = (var[tuple(slicer)].data == fill_value)
            elif "fill_value" in paraminfo.keys():
                fill_value = paraminfo["fill_value"]
                data['mask'] = np.isclose(var[tuple(slicer)], fill_value)
            else:
                data['mask'] = ~np.isfinite(var[tuple(slicer)].data)
            if isinstance(times, np.ma.MaskedArray):
                data['var'] = varconverter(var[tuple(slicer)].data)
            else:
                data['var'] = varconverter(var[tuple(slicer)])

            return data

    return retfunc



def reader_pollyraw(paraminfo):
    """build a function for reading in the polly raw data into larda"""
    def retfunc(f, time_interval, *further_intervals):
        """function that converts the netCDF to the larda container
        """
        logger.debug("filename at reader {}".format(f))
        import zipfile
        import os
        with zipfile.ZipFile(f) as zfile:
            path, file = os.path.split(f)
            ncD = netCDF4.Dataset('dummy', mode='r',
                    memory=zfile.read(file[:-4]))

            times = ncD.variables[paraminfo['time_variable']][:].astype(np.float64)

            timeconverter, _ = h.get_converter_array(
                paraminfo['time_conversion'], ncD=ncD)
            if isinstance(times, np.ma.MaskedArray):
                ts = timeconverter(times.data)
            else:
                ts = timeconverter(times)
            #get the time slicer from time_interval
            slicer = get_time_slicer(ts, f, time_interval)
            if slicer == None:
                return None

            #load just the first 2500 range bins of polly
            slicer.append(slice(0,2500))
            varconverter, maskconverter = h.get_converter_array(
                paraminfo['var_conversion'])

            varname, dim = paraminfo['variable_name'].split(':')
            slicer.append(int(dim))
            var = ncD.variables[varname]
            #print('var dict ',ncD.variables[paraminfo['variable_name']].__dict__)
            #print("time indices ", it_b, it_e)
            data = {}
            data['dimlabel'] = ['time', 'range']

            data["filename"] = f
            data["paraminfo"] = paraminfo
            data['ts'] = ts[tuple(slicer)[0]]

            data['system'] = paraminfo['system']
            data['name'] = paraminfo['paramkey']
            data['colormap'] = paraminfo['colormap']

            # experimental: put history into data container
            if 'identifier_history' in paraminfo and paraminfo['identifier_history'] != 'none':
                data['file_history'] = [ncD.getncattr(paraminfo['identifier_history'])]


            data['rg'] = np.arange(0,2500)

            data['rg_unit'] = 'range_bin'
            logger.debug('shapes {} {}'.format(ts.shape, var.shape))
            data['var_unit'] = get_var_attr_from_nc("identifier_var_unit",
                                                    paraminfo, var)
            data['var_lims'] = [float(e) for e in \
                                get_var_attr_from_nc("identifier_var_lims",
                                                     paraminfo, var)]

            # by default assume dimensions of (time, range, ...)
            # or define a custom order in the param toml file
            if 'dimorder' in paraminfo:
                slicer = [slicer[i] for i in paraminfo['dimorder']]

            if "identifier_fill_value" in paraminfo.keys() and not "fill_value" in paraminfo.keys():
                fill_value = var.getncattr(paraminfo['identifier_fill_value'])
                mask = (var[tuple(slicer)].data == fill_value)
            elif "fill_value" in paraminfo.keys():
                fill_value = paraminfo['fill_value']
                mask = np.isclose(var[tuple(slicer)].data, fill_value)
            else:
                mask = ~np.isfinite(var[tuple(slicer)].data)
            print(slicer)
            data['var'] = varconverter(var[tuple(slicer)].data)
            data['mask'] = maskconverter(mask)

            return data

    return retfunc
