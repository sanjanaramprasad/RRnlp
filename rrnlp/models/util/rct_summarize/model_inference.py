import pandas as pd
import warnings
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple, Union
import torch
import torch.distributed as dist
from torch.nn import functional as F
from transformers.generation_utils import *
from transformers.generation_beam_search import BeamScorer, BeamSearchScorer
from transformers.file_utils import ModelOutput
import pandas as pd
from transformers.generation_logits_process import (
    LogitsProcessorList  
)
from transformers.generation_stopping_criteria import (
    StoppingCriteriaList,
    validate_stopping_criteria,
)



BeamSearchOutput = Union[BeamSearchEncoderDecoderOutput, BeamSearchDecoderOnlyOutput]
class LogitsRecorder():
    def __init__(self, size):
        self.beam_ids = []
        self.beam_logits = []
        #print('SIZE', size)
        self.input_logits = torch.zeros(size)

    def _get_max_logits(self, logits_list_idx, next_tokens):
        logits_list_idx_tokens = []
        #print("token and logits", next_tokens, logits_list_idx)
        for i, logits in enumerate(logits_list_idx):
            token = next_tokens[i]
            token_logits = []
            #print(logits)
            for lm_head in logits:
                lm_head_score = lm_head[0].item()
                token_logits.append(lm_head_score)
                #print(token_logits)
            source_idx = token_logits.index(max(token_logits))
            #print(token_logits)   
            logits_list_idx_tokens.append(source_idx)
        logits_list_idx_tokens = torch.tensor([logits_list_idx_tokens])
       
        return logits_list_idx_tokens


    def process(self,
                input_ids, 
                next_tokens,
                next_indices, 
                logits_list):


        add_indices = (next_tokens).nonzero(as_tuple=True)[1]
        #if add_indices.numel():

        if True:
            finished_idx = next_indices[0][add_indices]
            finished_tokens = next_tokens[0][finished_idx]


            logits_list_idx_fin = logits_list[finished_idx]
            logits_list_idx_fin = self._get_max_logits(logits_list_idx_fin, finished_tokens)
            
            self.beam_ids += input_ids[finished_idx].clone()
            self.beam_logits += torch.cat([self.input_logits[finished_idx], logits_list_idx_fin.transpose(0,1)], dim = -1)

        unfinished_idx = (next_tokens != 2).nonzero(as_tuple=True)[1]
        unfinished_idx = next_indices[0][unfinished_idx][:4]
        unfinished_tokens = next_tokens[0][unfinished_idx]
        logits_list_idx = logits_list[unfinished_idx]
        logits_list_idx = self._get_max_logits(logits_list_idx, unfinished_tokens)
        self.input_logits = torch.cat([self.input_logits[unfinished_idx], logits_list_idx.transpose(0,1)], dim = -1)
        #print('NEXT TOKENS', next_tokens , next_indices)
        #print('LOGITS', self.input_logits) 
        return {'beam_ids' : self.beam_ids, 'beam_logits' : self.beam_logits}

            



class Data2TextGenerator(GenerationMixin):

    def __init__(self, model, tokenizer):
        self.model = model 
        self.tokenizer = tokenizer 
        self.config = self.model.config
        self.device = self.model.device
        #print(self.config.max_length)


    def _expand_inputs_for_generation(
        self,
        input_ids: torch.LongTensor,
        expand_size: int = 1,
        is_encoder_decoder: bool = False,
        attention_mask_col0: torch.LongTensor = None,
        attention_mask_col1: torch.LongTensor = None,
        attention_mask_col2: torch.LongTensor = None,
        attention_mask_col3: torch.LongTensor = None,
        attention_mask_col4: torch.LongTensor = None,
        encoder_outputs_col0: ModelOutput = None,
        encoder_outputs_col1: ModelOutput = None,
        encoder_outputs_col2: ModelOutput = None,
        encoder_outputs_col3: ModelOutput = None,
        encoder_outputs_col4: ModelOutput = None,
        **model_kwargs,
    ) -> Tuple[torch.LongTensor, Dict[str, Any]]:

        expanded_return_idx = (
            torch.arange(input_ids.shape[0]).view(-1, 1).repeat(1, expand_size).view(-1).to(input_ids.device)
        )
        input_ids = input_ids.index_select(0, expanded_return_idx)

        if "token_type_ids" in model_kwargs:
            token_type_ids = model_kwargs["token_type_ids"]
            model_kwargs["token_type_ids"] = token_type_ids.index_select(0, expanded_return_idx)

        if attention_mask_col0 is not None:
            model_kwargs["attention_mask_col0"] = attention_mask_col0.index_select(0, expanded_return_idx)
        if attention_mask_col1 is not None:
            model_kwargs["attention_mask_col1"] = attention_mask_col1.index_select(0, expanded_return_idx)
        if attention_mask_col2 is not None:
            model_kwargs["attention_mask_col2"] = attention_mask_col2.index_select(0, expanded_return_idx)
        if attention_mask_col3 is not None:
            model_kwargs["attention_mask_col3"] = attention_mask_col3.index_select(0, expanded_return_idx)
        if attention_mask_col4 is not None:
            model_kwargs["attention_mask_col4"] = attention_mask_col4.index_select(0, expanded_return_idx)
        global_attention_mask = model_kwargs.get("global_attention_mask", None)
        if global_attention_mask is not None:
            model_kwargs["global_attention_mask"] = global_attention_mask.index_select(0, expanded_return_idx)

        if is_encoder_decoder:
            if encoder_outputs_col0 is not None:
                encoder_outputs_col0["last_hidden_state"] = encoder_outputs_col0.last_hidden_state.index_select(
                    0, expanded_return_idx.to(encoder_outputs_col0.last_hidden_state.device)
                )
                model_kwargs["encoder_outputs_col0"] = encoder_outputs_col0

            if encoder_outputs_col1 is not None:
                encoder_outputs_col1["last_hidden_state"] = encoder_outputs_col1.last_hidden_state.index_select(
                    0, expanded_return_idx.to(encoder_outputs_col1.last_hidden_state.device)
                )
                model_kwargs["encoder_outputs_col1"] = encoder_outputs_col1


            if encoder_outputs_col2 is not None:
                encoder_outputs_col2["last_hidden_state"] = encoder_outputs_col2.last_hidden_state.index_select(
                    0, expanded_return_idx.to(encoder_outputs_col2.last_hidden_state.device)
                )
                model_kwargs["encoder_outputs_col2"] = encoder_outputs_col2

            if encoder_outputs_col3 is not None:
                encoder_outputs_col3["last_hidden_state"] = encoder_outputs_col3.last_hidden_state.index_select(
                    0, expanded_return_idx.to(encoder_outputs_col3.last_hidden_state.device)
                )
                model_kwargs["encoder_outputs_col3"] = encoder_outputs_col3

            if encoder_outputs_col4 is not None:
                encoder_outputs_col4["last_hidden_state"] = encoder_outputs_col4.last_hidden_state.index_select(
                    0, expanded_return_idx.to(encoder_outputs_col4.last_hidden_state.device)
                )
                model_kwargs["encoder_outputs_col4"] = encoder_outputs_col4


        return input_ids, model_kwargs


   
    def _prepare_attention_mask_for_generation(self, batch, device, model_kwargs):
        input_ids_col0 = batch[0]
        attention_mask_col0 = batch[1] if len(batch) >1 else None
        attention_mask_col1 = batch[3] if len(batch) >3 else None
        attention_mask_col2 = batch[5] if len(batch) >5 else None
        attention_mask_col3 = batch[7] if len(batch) >5 else None
        
        if not(attention_mask_col0 is None):
            model_kwargs["attention_mask_col0"] = attention_mask_col0
            model_kwargs["attention_mask_col0"] = model_kwargs["attention_mask_col0"].to(device)

        if not(attention_mask_col1 is None):
            model_kwargs["attention_mask_col1"] = attention_mask_col1
            model_kwargs["attention_mask_col1"] = model_kwargs["attention_mask_col1"].to(device)

        if not(attention_mask_col2 is None):
            model_kwargs["attention_mask_col2"] = attention_mask_col2
            model_kwargs["attention_mask_col2"] = model_kwargs["attention_mask_col2"].to(device)

        if not(attention_mask_col3 is None):
            model_kwargs["attention_mask_col3"] = attention_mask_col3
            model_kwargs["attention_mask_col3"] = model_kwargs["attention_mask_col3"].to(device)

        if model_kwargs['background_lm']:
            empty_input_attn_mask = torch.tensor([[1, 1] + [0] * 254])
            empty_input_attn_mask = empty_input_attn_mask.to(device = device)
            model_kwargs['attention_mask_col4'] = empty_input_attn_mask

        global_attention_mask = global_attention_mask = torch.zeros_like(input_ids_col0)
        global_attention_mask[:, 0] = 1
        global_attention_mask = global_attention_mask.to(device)
        model_kwargs['global_attention_mask'] = global_attention_mask

        #print(model_kwargs)
        return model_kwargs

    def _prepare_encoder_decoder_kwargs_for_generation(
        self, input_ids_col0: torch.LongTensor,
        input_ids_col1: torch.LongTensor,
        input_ids_col2: torch.LongTensor,
        input_ids_col3: torch.LongTensor,
        device,
        model_kwargs
    ) -> Dict[str, Any]:
        if "encoder_outputs" not in model_kwargs:
            
            # retrieve encoder hidden states
            encoder_col = self.model.get_encoder()
            encoder_kwargs = {
                argument: value for argument, value in model_kwargs.items() if not argument.startswith("decoder_")
            }
            
            if not(input_ids_col0 is None):
                encoder_kwargs = {argument: value for argument, value in model_kwargs.items() if  "col" not in argument and 'back' not in argument and 'decoder' not in argument}
                attention_mask_col0 = model_kwargs.get("attention_mask_col0", None)
                encoder_kwargs["attention_mask"] = attention_mask_col0
                global_attention_mask = model_kwargs.get("global_attention_mask", None)
                encoder_kwargs["global_attention_mask"] = global_attention_mask
                
                #encoder_outputs = encoder_kwargs.get('encoder_outputs_col0', None)
                
                model_kwargs["encoder_outputs_col0"]: ModelOutput = self.model.get_encoder()(input_ids_col0, return_dict=True, **encoder_kwargs)

            if not(input_ids_col1 is None):
                    encoder_kwargs = {argument: value for argument, value in model_kwargs.items() if  "col" not in argument and 'back' not in argument and 'decoder' not in argument}
                    attention_mask_col1 = model_kwargs.get("attention_mask_col1", None)
                    encoder_kwargs["attention_mask"] = attention_mask_col1
                    global_attention_mask = model_kwargs.get("global_attention_mask", None)
                    encoder_kwargs["global_attention_mask"] = global_attention_mask
                    #encoder_outputs = encoder_kwargs.get('encoder_outputs_col1', None)

                    model_kwargs["encoder_outputs_col1"]: ModelOutput = self.model.get_encoder()(input_ids_col1, return_dict=True, **encoder_kwargs)

            if not(input_ids_col2 is None):
                    encoder_kwargs = {argument: value for argument, value in model_kwargs.items() if "col" not in argument and 'back' not in argument and 'decoder' not in argument}
                    attention_mask_col2 = model_kwargs.get("attention_mask_col2", None)
                    encoder_kwargs["attention_mask"] = attention_mask_col2
                    global_attention_mask = model_kwargs.get("global_attention_mask", None)
                    encoder_kwargs["global_attention_mask"] = global_attention_mask
                    #print(encoder_kwargs)
                    #encoder_outputs = encoder_kwargs.get('encoder_outputs_col2', None)

                    model_kwargs["encoder_outputs_col2"]: ModelOutput = self.model.get_encoder()(input_ids_col2, return_dict=True, **encoder_kwargs)
            
            if not(input_ids_col3 is None):
                    encoder_kwargs = {argument: value for argument, value in model_kwargs.items() if "col" not in argument and 'back' not in argument and 'decoder' not in argument}
                    attention_mask_col3 = model_kwargs.get("attention_mask_col3", None)
                    encoder_kwargs["attention_mask"] = attention_mask_col3
                    global_attention_mask = model_kwargs.get("global_attention_mask", None)
                    encoder_kwargs["global_attention_mask"] = global_attention_mask
                    #print(encoder_kwargs)
                    #encoder_outputs = encoder_kwargs.get('encoder_outputs_col2', None)

                    model_kwargs["encoder_outputs_col3"]: ModelOutput = self.model.get_encoder()(input_ids_col3, return_dict=True, **encoder_kwargs)
                     
            if model_kwargs['background_lm']:
                    encoder_kwargs = {argument: value for argument, value in model_kwargs.items() if "col" not in argument and 'back' not in argument and 'decoder' not in argument}
                    empty_input_ids = torch.tensor([[0,2] + [1] * 254])
                    empty_input_ids = empty_input_ids.to(device = device)
                    attention_mask_col4 = model_kwargs.get("attention_mask_col4", None)
                    encoder_kwargs["attention_mask"] = attention_mask_col4
                    global_attention_mask = None
                    encoder_kwargs["global_attention_mask"] = None
                    #print(encoder_kwargs)
                    #encoder_outputs = encoder_kwargs.get('encoder_outputs_col2', None)

                    model_kwargs["encoder_outputs_col4"]: ModelOutput = self.model.get_encoder()(empty_input_ids, return_dict=True, **encoder_kwargs)
                     


            model_kwargs["attention_mask_col0"] = attention_mask_col0
            model_kwargs["attention_mask_col1"] = attention_mask_col1
            model_kwargs["attention_mask_col2"] = attention_mask_col2
            model_kwargs["attention_mask_col3"] = attention_mask_col3
            if model_kwargs['background_lm']:
                model_kwargs['attention_mask_col4'] = attention_mask_col4
            model_kwargs['global_attention_mask'] = global_attention_mask

        return model_kwargs
        
    def generate(self,
        batch,
        input_ids = None,
        max_length: Optional[int] = None,
        min_length: Optional[int] = None,
        do_sample: Optional[bool] = None,
        early_stopping: Optional[bool] = None,
        num_beams: Optional[int] = None,
        temperature: Optional[float] = None,
        top_k: Optional[int] = None,
        top_p: Optional[float] = None,
        repetition_penalty: Optional[float] = None,
        bad_words_ids: Optional[Iterable[int]] = None,
        bos_token_id: Optional[int] = None,
        pad_token_id: Optional[int] = None,
        eos_token_id: Optional[int] = None,
        length_penalty: Optional[float] = None,
        no_repeat_ngram_size: Optional[int] = None,
        encoder_no_repeat_ngram_size: Optional[int] = None,
        num_return_sequences: Optional[int] = None,
        max_time: Optional[float] = None,
        max_new_tokens: Optional[int] = None,
        decoder_start_token_id: Optional[int] = None,
        use_cache: Optional[bool] = None,
        num_beam_groups: Optional[int] = None,
        diversity_penalty: Optional[float] = None,
        prefix_allowed_tokens_fn: Optional[Callable[[int, torch.Tensor], List[int]]] = None,
        output_attentions: Optional[bool] = None,
        output_hidden_states: Optional[bool] = True,
        output_scores: Optional[bool] = None,
        return_dict_in_generate: Optional[bool] = None,
        forced_bos_token_id: Optional[int] = None,
        forced_eos_token_id: Optional[int] = None,
        remove_invalid_values: Optional[bool] = None,
        synced_gpus: Optional[bool] = None,
        control_key = None,
        background_lm = False,
        device = torch.device('cuda'),
        **model_kwargs, 
    ):
        #return_dict_in_generate = None
        #print("USE CACHE", use_cache)
        #use_cache = False
        #use_cache = True
        cur_len = batch[0].shape[-1]
        input_ids_col0 = batch[0] if len(batch) >1 else None
        input_ids_col0 = input_ids_col0.to(device)
        attention_mask_col0 = batch[1] if len(batch) >1 else None
        attention_mask_col0 = attention_mask_col0.to(device)

        input_ids_col1 = batch[2] if len(batch) >3 else None
        input_ids_col1 = input_ids_col1.to(device)
        attention_mask_col1 = batch[3] if len(batch) >3 else None
        attention_mask_col1 = attention_mask_col1.to(device)

        input_ids_col2 = batch[4] if len(batch) >5 else None
        input_ids_col2 = input_ids_col2.to(device)
        attention_mask_col2 = batch[5] if len(batch) >5 else None
        attention_mask_col2 = attention_mask_col2.to(device)

        input_ids_col3 = batch[6] if len(batch) >5 else None
        input_ids_col3 = input_ids_col3.to(device)
        attention_mask_col3 = batch[7] if len(batch) >5 else None
        attention_mask_col3 = attention_mask_col3.to(device)
        
        ##print('INPUT IDS', input_ids)   
        #max_length = max_length if max_length is not None else self.config.max_length
        # set init values
        if max_length is None and max_new_tokens is None:
            # Both are None, default
            max_length = self.config.max_length
        elif max_length is not None and max_new_tokens is not None:
            # Both are set, this is odd, raise a warning
            warnings.warn(
                "Both `max_length` and `max_new_tokens` have been set but they serve the same purpose.", UserWarning
            )
        num_beams = num_beams if num_beams is not None else self.config.num_beams
        num_beam_groups = num_beam_groups if num_beam_groups is not None else self.config.num_beam_groups
        do_sample = do_sample if do_sample is not None else self.config.do_sample
        num_return_sequences = (
            num_return_sequences if num_return_sequences is not None else self.config.num_return_sequences
        )

        pad_token_id = pad_token_id if pad_token_id is not None else self.config.pad_token_id
        bos_token_id = bos_token_id if bos_token_id is not None else self.config.eos_token_id


        output_scores = output_scores if output_scores is not None else self.config.output_scores
        output_attentions = output_attentions if output_attentions is not None else self.config.output_attentions
        output_hidden_states = (
            output_hidden_states if output_hidden_states is not None else self.config.output_hidden_states
        )
        return_dict_in_generate = (
            return_dict_in_generate if return_dict_in_generate is not None else self.config.return_dict_in_generate
        )

        model_kwargs["output_attentions"] = output_attentions
        model_kwargs["output_hidden_states"] = output_hidden_states
        model_kwargs['background_lm'] = background_lm
        ##model_kwargs['background_lm'] = background_lm
        #model_kwargs["control_key"] = None

        '''if input_ids is None and "inputs_embeds" not in model_kwargs:
            # init `input_ids` with bos_token_id
            input_ids = self._prepare_input_ids_for_generation(bos_token_id, model_kwargs.get("encoder_outputs"))
        '''

        if model_kwargs.get("attention_mask", None) is None:
            # init `attention_mask` depending on `pad_token_id`
            model_kwargs =  self._prepare_attention_mask_for_generation(
                batch, device, model_kwargs)

        encoder_input_ids = input_ids if self.config.is_encoder_decoder else None
        input_list = [each for each in [input_ids_col0, input_ids_col1, input_ids_col2] \
                            if not(each is None)]
        encoder_input_ids = torch.cat(input_list, 0)
        if self.config.is_encoder_decoder:
            # add encoder_outputs to model_kwargs
            model_kwargs = self._prepare_encoder_decoder_kwargs_for_generation(input_ids_col0, 
                                                                                input_ids_col1,
                                                                                input_ids_col2,
                                                                                input_ids_col3,
                                                                                device,
                                                                                model_kwargs,
              
                                                                      )

            if input_ids is not None:
                input_ids = input_ids
             
            elif "decoder_input_ids" in model_kwargs:
                input_ids = model_kwargs.pop("decoder_input_ids")
            else:
                input_ids = self._prepare_input_ids_for_generation(bos_token_id, model_kwargs.get("encoder_outputs"))
                input_ids = self._prepare_decoder_input_ids_for_generation(
                    input_ids, decoder_start_token_id=decoder_start_token_id, bos_token_id=bos_token_id
                )
            ##print('DECODER INPUT IDS', input_ids)

            
        #print(model_kwargs)    
        is_greedy_gen_mode = (num_beams == 1) and (num_beam_groups == 1) and do_sample is False
        
        is_sample_gen_mode = (num_beams == 1) and (num_beam_groups == 1) and do_sample is True
        is_beam_gen_mode = (num_beams > 1) and (num_beam_groups == 1) and do_sample is False
        is_beam_sample_gen_mode = (num_beams > 1) and (num_beam_groups == 1) and do_sample is True
        is_group_beam_gen_mode = (num_beams > 1) and (num_beam_groups > 1)
        if num_beam_groups > num_beams:
            raise ValueError("`num_beam_groups` has to be smaller or equal to `num_beams`")
        if is_group_beam_gen_mode and do_sample is True:
            raise ValueError(
                "Diverse beam search cannot be used in sampling mode. Make sure that `do_sample` is set to `False`."
            )

        # set model_kwargs
        model_kwargs["use_cache"] = use_cache
        model_kwargs["control_key"] = control_key 
        model_kwargs["inference"] = True

        # get distribution pre_processing samplers
        logits_processor = self._get_logits_processor(
            repetition_penalty=repetition_penalty,
            no_repeat_ngram_size=no_repeat_ngram_size,
            encoder_no_repeat_ngram_size=encoder_no_repeat_ngram_size,
            encoder_input_ids=encoder_input_ids,
            bad_words_ids=bad_words_ids,
            min_length=min_length,
            max_length=max_length,
            eos_token_id=eos_token_id,
            forced_bos_token_id=forced_bos_token_id,
            forced_eos_token_id=forced_eos_token_id,
            prefix_allowed_tokens_fn=prefix_allowed_tokens_fn,
            num_beams=num_beams,
            num_beam_groups=num_beam_groups,
            diversity_penalty=diversity_penalty,
            remove_invalid_values=remove_invalid_values,
        )

        cur_len = input_ids.shape[-1]
        stopping_criteria = self._get_stopping_criteria(max_length=max_length,  max_time=max_time, max_new_tokens=max_new_tokens, start_length=cur_len)

        if is_greedy_gen_mode:
            #print("GREEDY SEARCHING")
            if num_return_sequences > 1:
                raise ValueError(
                    f"num_return_sequences has to be 1, but is {num_return_sequences} when doing greedy search."
                )

            # greedy search
            return self.model.greedy_search(
                input_ids,
                logits_processor=logits_processor,
                stopping_criteria=stopping_criteria,
                pad_token_id=pad_token_id,
                eos_token_id=eos_token_id,
                output_scores=output_scores,
                return_dict_in_generate=return_dict_in_generate,
                synced_gpus=synced_gpus,
                **model_kwargs,
            )

        elif is_beam_gen_mode:
            #print("BEAM SEARCHING")
            batch_size = input_ids.shape[0]

            length_penalty = length_penalty if length_penalty is not None else self.config.length_penalty
            early_stopping = early_stopping if early_stopping is not None else self.config.early_stopping

            if num_return_sequences > num_beams:
                raise ValueError("`num_return_sequences` has to be smaller or equal to `num_beams`.")

            if stopping_criteria.max_length is None:
                raise ValueError("`max_length` needs to be a stopping_criteria for now.")

            beam_scorer = BeamSearchScorer(
                batch_size=batch_size,
                num_beams=num_beams,
                device=self.device,
                length_penalty=length_penalty,
                do_early_stopping=early_stopping,
                num_beam_hyps_to_keep=num_return_sequences,
            )
            # interleave with `num_beams`
            input_ids, model_kwargs = self._expand_inputs_for_generation(
                input_ids, expand_size=num_beams, is_encoder_decoder=self.config.is_encoder_decoder, **model_kwargs
            )
            #print('INPUT IDS', input_ids)
            ##print("BEAM SEARCH KWARGS", model_kwargs)
            return self._beam_searcher(
                input_ids,
                beam_scorer,
                logits_processor=logits_processor,
                stopping_criteria=stopping_criteria,
                pad_token_id=pad_token_id,
                eos_token_id=eos_token_id,
                output_scores=output_scores,
                return_dict_in_generate=return_dict_in_generate,
                synced_gpus=synced_gpus,
                **model_kwargs,
            )


        elif is_group_beam_gen_mode:
            #print("GROUP BEAM SEARCHING")
            batch_size = input_ids.shape[0]
            length_penalty = length_penalty if length_penalty is not None else self.config.length_penalty
            early_stopping = early_stopping if early_stopping is not None else self.config.early_stopping

            if num_return_sequences > num_beams:
                raise ValueError("`num_return_sequences` has to be smaller or equal to `num_beams`.")

            if num_beams % num_beam_groups != 0:
                raise ValueError("`num_beams` should be divisible by `num_beam_groups` for group beam search.")

            if stopping_criteria.max_length is None:
                raise ValueError("`max_length` needs to be a stopping_criteria for now.")

            diverse_beam_scorer = BeamSearchScorer(
                batch_size=batch_size,
                num_beams=num_beams,
                max_length=stopping_criteria.max_length,
                device=self.device,
                length_penalty=length_penalty,
                do_early_stopping=early_stopping,
                num_beam_hyps_to_keep=num_return_sequences,
                num_beam_groups=num_beam_groups,
            )
            # interleave with `num_beams`
            input_ids, model_kwargs = self._expand_inputs_for_generation(
                input_ids, expand_size=num_beams, is_encoder_decoder=self.config.is_encoder_decoder, **model_kwargs
            )
            return self.model.group_beam_search(
                input_ids,
                diverse_beam_scorer,
                logits_processor=logits_processor,
                stopping_criteria=stopping_criteria,
                pad_token_id=pad_token_id,
                eos_token_id=eos_token_id,
                output_scores=output_scores,
                return_dict_in_generate=return_dict_in_generate,
                synced_gpus=synced_gpus,
                **model_kwargs,
            )

        elif is_sample_gen_mode:
            # get probability distribution warper
            logits_warper = self._get_logits_warper(
                top_k=top_k, top_p=top_p, temperature=temperature, num_beams=num_beams
            )

            # expand input_ids with `num_return_sequences` additional sequences per batch
            input_ids, model_kwargs = self._expand_inputs_for_generation(
                input_ids,
                expand_size=num_return_sequences,
                is_encoder_decoder=self.config.is_encoder_decoder,
                **model_kwargs,
            )

            # sample
            return self.model.sample(
                input_ids,
                logits_processor=logits_processor,
                logits_warper=logits_warper,
                stopping_criteria=stopping_criteria,
                pad_token_id=pad_token_id,
                eos_token_id=eos_token_id,
                output_scores=output_scores,
                return_dict_in_generate=return_dict_in_generate,
                synced_gpus=synced_gpus,
                **model_kwargs,
            )
        elif is_beam_sample_gen_mode:
            logits_warper = self._get_logits_warper(
                top_k=top_k, top_p=top_p, temperature=temperature, num_beams=num_beams
            )

            batch_size = input_ids.shape[0] * num_return_sequences

            length_penalty = length_penalty if length_penalty is not None else self.config.length_penalty
            if stopping_criteria.max_length is None:
                raise ValueError("`max_length` needs to be a stopping_criteria for now.")

            beam_scorer = BeamSearchScorer(
                batch_size=batch_size,
                num_beams=num_beams,
                device=self.device,
                length_penalty=length_penalty,
                do_early_stopping=early_stopping,
            )

            # interleave with `num_beams * num_return_sequences`
            input_ids, model_kwargs = self._expand_inputs_for_generation(
                input_ids,
                expand_size=num_beams * num_return_sequences,
                is_encoder_decoder=self.config.is_encoder_decoder,
                **model_kwargs,
            )

            return self._beam_sample(
                input_ids,
                beam_scorer,
                logits_processor=logits_processor,
                logits_warper=logits_warper,
                stopping_criteria=stopping_criteria,
                pad_token_id=pad_token_id,
                eos_token_id=eos_token_id,
                output_scores=output_scores,
                return_dict_in_generate=return_dict_in_generate,
                synced_gpus=synced_gpus,
                **model_kwargs,
            )

    def _beam_sample(
        self,
        input_ids: torch.LongTensor,
        beam_scorer: BeamScorer,
        logits_processor: Optional[LogitsProcessorList] = None,
        stopping_criteria: Optional[StoppingCriteriaList] = None,
        logits_warper: Optional[LogitsProcessorList] = None,
        max_length: Optional[int] = None,
        pad_token_id: Optional[int] = None,
        eos_token_id: Optional[int] = None,
        output_attentions: Optional[bool] = None,
        output_hidden_states: Optional[bool] = None,
        output_scores: Optional[bool] = None,
        return_dict_in_generate: Optional[bool] = None,
        synced_gpus: Optional[bool] = None,
        **model_kwargs,
    ) -> Union[BeamSampleOutput, torch.LongTensor]:
        r"""
        Generates sequences for models with a language modeling head using beam search with multinomial sampling.
        Parameters:
            input_ids (:obj:`torch.LongTensor` of shape :obj:`(batch_size, sequence_length)`, `optional`):
                The sequence used as a prompt for the generation. If :obj:`None` the method initializes it as an empty
                :obj:`torch.LongTensor` of shape :obj:`(1,)`.
            beam_scorer (:obj:`BeamScorer`):
                A derived instance of :class:`~transformers.BeamScorer` that defines how beam hypotheses are
                constructed, stored and sorted during generation. For more information, the documentation of
                :class:`~transformers.BeamScorer` should be read.
            logits_processor (:obj:`LogitsProcessorList`, `optional`):
                An instance of :class:`~transformers.LogitsProcessorList`. List of instances of class derived from
                :class:`~transformers.LogitsProcessor` used to modify the prediction scores of the language modeling
                head applied at each generation step.
            stopping_criteria (:obj:`StoppingCriteriaList`, `optional`):
                An instance of :class:`~transformers.StoppingCriteriaList`. List of instances of class derived from
                :class:`~transformers.StoppingCriteria` used to tell if the generation loop should stop.
            logits_warper (:obj:`LogitsProcessorList`, `optional`):
                An instance of :class:`~transformers.LogitsProcessorList`. List of instances of class derived from
                :class:`~transformers.LogitsWarper` used to warp the prediction score distribution of the language
                modeling head applied before multinomial sampling at each generation step.
            max_length (:obj:`int`, `optional`, defaults to 20):
                **DEPRECATED**. Use :obj:`logits_processor` or :obj:`stopping_criteria` directly to cap the number of
                generated tokens. The maximum length of the sequence to be generated.
            pad_token_id (:obj:`int`, `optional`):
                The id of the `padding` token.
            eos_token_id (:obj:`int`, `optional`):
                The id of the `end-of-sequence` token.
            output_attentions (:obj:`bool`, `optional`, defaults to `False`):
                Whether or not to return the attentions tensors of all attention layers. See ``attentions`` under
                returned tensors for more details.
            output_hidden_states (:obj:`bool`, `optional`, defaults to `False`):
                Whether or not to return trhe hidden states of all layers. See ``hidden_states`` under returned tensors
                for more details.
            output_scores (:obj:`bool`, `optional`, defaults to `False`):
                Whether or not to return the prediction scores. See ``scores`` under returned tensors for more details.
            return_dict_in_generate (:obj:`bool`, `optional`, defaults to `False`):
                Whether or not to return a :class:`~transformers.file_utils.ModelOutput` instead of a plain tuple.
            synced_gpus (:obj:`bool`, `optional`, defaults to :obj:`False`):
                Whether to continue running the while loop until max_length (needed for ZeRO stage 3)
            model_kwargs:
                Additional model specific kwargs will be forwarded to the :obj:`forward` function of the model. If
                model is an encoder-decoder model the kwargs should include :obj:`encoder_outputs`.
        Return:
            :class:`~transformers.generation_utils.BeamSampleDecoderOnlyOutput`,
            :class:`~transformers.generation_utils.BeamSampleEncoderDecoderOutput` or obj:`torch.LongTensor`: A
            :obj:`torch.LongTensor` containing the generated tokens (default behaviour) or a
            :class:`~transformers.generation_utils.BeamSampleDecoderOnlyOutput` if
            ``model.config.is_encoder_decoder=False`` and ``return_dict_in_generate=True`` or a
            :class:`~transformers.generation_utils.BeamSampleEncoderDecoderOutput` if
            ``model.config.is_encoder_decoder=True``.
        Examples::
            >>> from transformers import (
            ...     AutoTokenizer,
            ...     AutoModelForSeq2SeqLM,
            ...     LogitsProcessorList,
            ...     MinLengthLogitsProcessor,
            ...     TopKLogitsWarper,
            ...     TemperatureLogitsWarper,
            ...     BeamSearchScorer,
            ... )
            >>> import torch
            >>> tokenizer = AutoTokenizer.from_pretrained("t5-base")
            >>> model = AutoModelForSeq2SeqLM.from_pretrained("t5-base")
            >>> encoder_input_str = "translate English to German: How old are you?"
            >>> encoder_input_ids = tokenizer(encoder_input_str, return_tensors="pt").input_ids
            >>> # lets run beam search using 3 beams
            >>> num_beams = 3
            >>> # define decoder start token ids
            >>> input_ids = torch.ones((num_beams, 1), device=model.device, dtype=torch.long)
            >>> input_ids = input_ids * model.config.decoder_start_token_id
            >>> # add encoder_outputs to model keyword arguments
            >>> model_kwargs = {
            ...     "encoder_outputs": model.get_encoder()(encoder_input_ids.repeat_interleave(num_beams, dim=0), return_dict=True)
            ... }
            >>> # instantiate beam scorer
            >>> beam_scorer = BeamSearchScorer(
            ...     batch_size=1,
            ...     max_length=model.config.max_length,
            ...     num_beams=num_beams,
            ...     device=model.device,
            ... )
            >>> # instantiate logits processors
            >>> logits_processor = LogitsProcessorList([
            ...     MinLengthLogitsProcessor(5, eos_token_id=model.config.eos_token_id)
            ... ])
            >>> # instantiate logits processors
            >>> logits_warper = LogitsProcessorList([
            ...     TopKLogitsWarper(50),
            ...     TemperatureLogitsWarper(0.7),
            ... ])
            >>> outputs = model.beam_sample(
            ...     input_ids, beam_scorer, logits_processor=logits_processor, logits_warper=logits_warper, **model_kwargs
            ... )
            >>> print("Generated:", tokenizer.batch_decode(outputs, skip_special_tokens=True))
        """
        # init values
        logits_processor = logits_processor if logits_processor is not None else LogitsProcessorList()
        stopping_criteria = stopping_criteria if stopping_criteria is not None else StoppingCriteriaList()
        if max_length is not None:
            warnings.warn(
                "`max_length` is deprecated in this function, use `stopping_criteria=StoppingCriteriaList(MaxLengthCriteria(max_length=max_length))` instead.",
                UserWarning,
            )
            stopping_criteria = validate_stopping_criteria(stopping_criteria, max_length)
        pad_token_id = pad_token_id if pad_token_id is not None else self.config.pad_token_id
        eos_token_id = eos_token_id if eos_token_id is not None else self.config.eos_token_id
        output_scores = output_scores if output_scores is not None else self.config.output_scores
        output_attentions = output_attentions if output_attentions is not None else self.config.output_attentions
        output_hidden_states = (
            output_hidden_states if output_hidden_states is not None else self.config.output_hidden_states
        )
        return_dict_in_generate = (
            return_dict_in_generate if return_dict_in_generate is not None else self.config.return_dict_in_generate
        )

        # init attention / hidden states / scores tuples
        scores = () if (return_dict_in_generate and output_scores) else None
        decoder_attentions = () if (return_dict_in_generate and output_attentions) else None
        cross_attentions = () if (return_dict_in_generate and output_attentions) else None
        decoder_hidden_states = () if (return_dict_in_generate and output_hidden_states) else None

        # if model is an encoder-decoder, retrieve encoder attention weights and hidden states
        if return_dict_in_generate and self.config.is_encoder_decoder:
            encoder_attentions = model_kwargs["encoder_outputs"].get("attentions") if output_attentions else None
            encoder_hidden_states = (
                model_kwargs["encoder_outputs"].get("hidden_states") if output_hidden_states else None
            )

        batch_size = len(beam_scorer._beam_hyps)
        num_beams = beam_scorer.num_beams

        batch_beam_size, cur_len = input_ids.shape

        beam_scores = torch.zeros((batch_size, num_beams), dtype=torch.float, device=input_ids.device)
        beam_scores = beam_scores.view((batch_size * num_beams,))
        logits_recorder = LogitsRecorder(size = input_ids.shape)
        this_peer_finished = False  # used by synced_gpus only
        while True:

            if synced_gpus:
                # Under synced_gpus the `forward` call must continue until all gpus complete their sequence.
                # The following logic allows an early break if all peers finished generating their sequence
                this_peer_finished_flag = torch.tensor(0.0 if this_peer_finished else 1.0).to(input_ids.device)
                # send 0.0 if we finished, 1.0 otherwise
                dist.all_reduce(this_peer_finished_flag, op=dist.ReduceOp.SUM)
                # did all peers finish? the reduced sum will be 0.0 then
                if this_peer_finished_flag.item() == 0.0:
                    break

            model_inputs = self.model.prepare_inputs_for_generation(input_ids, **model_kwargs)

            outputs = self.model(
                **model_inputs,
                return_dict=True,
                output_attentions=output_attentions,
                output_hidden_states=output_hidden_states,
            )

            if synced_gpus and this_peer_finished:
                cur_len = cur_len + 1
                continue  # don't waste resources running the code we don't need

            next_token_logits = outputs.logits[:, -1, :]

            # hack: adjust tokens for Marian. For Marian we have to make sure that the `pad_token_id`
            # cannot be generated both before and after the `F.log_softmax` operation.
            next_token_logits = self.adjust_logits_during_generation(next_token_logits, cur_len=cur_len)
            next_token_scores = F.log_softmax(next_token_logits, dim=-1)  # (batch_size * num_beams, vocab_size)

            next_token_scores = logits_processor(input_ids, next_token_scores)
            next_token_scores = next_token_scores + beam_scores[:, None].expand_as(next_token_scores)
            next_token_scores = logits_warper(input_ids, next_token_scores)

            # Store scores, attentions and hidden_states when required
            if return_dict_in_generate:
                if output_scores:
                    scores += (next_token_scores,)
                if output_attentions:
                    decoder_attentions += (
                        (outputs.decoder_attentions,) if self.config.is_encoder_decoder else (outputs.attentions,)
                    )
                    if self.config.is_encoder_decoder:
                        cross_attentions += (outputs.cross_attentions,)

                if output_hidden_states:
                    decoder_hidden_states += (
                        (outputs.decoder_hidden_states,)
                        if self.config.is_encoder_decoder
                        else (outputs.hidden_states,)
                    )

            # reshape for beam search
            vocab_size = next_token_scores.shape[-1]
            next_token_scores = next_token_scores.view(batch_size, num_beams * vocab_size)

            probs = F.softmax(next_token_scores, dim=-1)

            next_tokens = torch.multinomial(probs, num_samples=2 * num_beams)
            next_token_scores = torch.gather(next_token_scores, -1, next_tokens)

            next_token_scores, _indices = torch.sort(next_token_scores, descending=True, dim=1)
            next_tokens = torch.gather(next_tokens, -1, _indices)

            next_indices = next_tokens // vocab_size
            next_tokens = next_tokens % vocab_size

            logits_list = outputs.lm_logits_individual
            logits_recorder_outputs = logits_recorder.process(
                input_ids, 
                next_tokens,
                next_indices, 
                logits_list
            )
            # stateless
            beam_outputs = beam_scorer.process(
                input_ids,
                next_token_scores,
                next_tokens,
                next_indices,
                pad_token_id=pad_token_id,
                eos_token_id=eos_token_id,
            )
            beam_scores = beam_outputs["next_beam_scores"]
            beam_next_tokens = beam_outputs["next_beam_tokens"]
            beam_idx = beam_outputs["next_beam_indices"]

            input_ids = torch.cat([input_ids[beam_idx, :], beam_next_tokens.unsqueeze(-1)], dim=-1)

            model_kwargs = self._update_model_kwargs_for_generation(
                outputs, model_kwargs, is_encoder_decoder=self.config.is_encoder_decoder
            )

            if model_kwargs["past"] is not None:
                model_kwargs["past"] = self.model._reorder_cache(model_kwargs["past"], beam_idx)

            # increase cur_len
            cur_len = cur_len + 1

            if beam_scorer.is_done or stopping_criteria(input_ids, scores):
                if not synced_gpus:
                    break
                else:
                    this_peer_finished = True

        sequence_outputs = beam_scorer.finalize(
            input_ids,
            beam_scores,
            next_tokens,
            next_indices,
            pad_token_id=pad_token_id,
            eos_token_id=eos_token_id,
            max_length=stopping_criteria.max_length,
        )
        indices = []
        seq_outputs = sequence_outputs["sequences"][0][:-1]
        
        #if seq_outputs.shape[-1] == 1023:
        #print('SEQUENCES', sequence_outputs, ' '.join([self.tokenizer.decode(w) for w in sequence_outputs["sequences"][0]]))
        seq_len = len(seq_outputs)
        #print(logits_recorder_outputs['beam_ids'])
        
        for i, iid in enumerate(logits_recorder_outputs['beam_ids']):
         #print("COMPARE", seq_outputs.shape[-1], iid.shape)
         iid = iid[:seq_len]
         if iid.shape == seq_outputs.shape:
             #print("COMPARE", seq_outputs, iid)
             #print(iid.eq(seq_outputs))
             #print('-' * 13)
             if torch.all(iid.eq(seq_outputs)):
                indices.append(i)
                break

        if return_dict_in_generate:
            if not output_scores:
                sequence_outputs["sequence_scores"] = None
            if self.config.is_encoder_decoder:
                return BeamSampleEncoderDecoderOutput(
                    sequences=sequence_outputs["sequences"],
                    sequences_scores=sequence_outputs["sequence_scores"],
                    scores=scores,
                    encoder_attentions=encoder_attentions,
                    encoder_hidden_states=encoder_hidden_states,
                    decoder_attentions=decoder_attentions,
                    cross_attentions=cross_attentions,
                    decoder_hidden_states=decoder_hidden_states,
                )
            else:
                return BeamSampleDecoderOnlyOutput(
                    sequences=sequence_outputs["sequences"],
                    sequences_scores=sequence_outputs["sequence_scores"],
                    scores=scores,
                    attentions=decoder_attentions,
                    hidden_states=decoder_hidden_states,
                )
        else:
            logits_scores = logits_recorder_outputs['beam_logits'][indices[0]] if indices != [] else [] 
            return sequence_outputs["sequences"], logits_scores


    def _beam_searcher(
        self,
        input_ids: torch.LongTensor,
        beam_scorer: BeamScorer,
        logits_processor: Optional[LogitsProcessorList] = None,
        stopping_criteria: Optional[StoppingCriteriaList] = None,
        max_length: Optional[int] = None,
        pad_token_id: Optional[int] = None,
        eos_token_id: Optional[int] = None,
        output_attentions: Optional[bool] = None,
        output_hidden_states: Optional[bool] = None,
        output_scores: Optional[bool] = None,
        return_dict_in_generate: Optional[bool] = None,
        synced_gpus: Optional[bool] = None,
        **model_kwargs,
        ) -> Union[BeamSearchOutput, torch.LongTensor]:
        r"""
        Generates sequences for models with a language modeling head using beam search decoding.
        Parameters:
            input_ids (:obj:`torch.LongTensor` of shape :obj:`(batch_size, sequence_length)`, `optional`):
                The sequence used as a prompt for the generation. If :obj:`None` the method initializes it as an empty
                :obj:`torch.LongTensor` of shape :obj:`(1,)`.
            beam_scorer (:obj:`BeamScorer`):
                An derived instance of :class:`~transformers.BeamScorer` that defines how beam hypotheses are
                constructed, stored and sorted during generation. For more information, the documentation of
                :class:`~transformers.BeamScorer` should be read.
            logits_processor (:obj:`LogitsProcessorList`, `optional`):
                An instance of :class:`~transformers.LogitsProcessorList`. List of instances of class derived from
                :class:`~transformers.LogitsProcessor` used to modify the prediction scores of the language modeling
                head applied at each generation step.
            stopping_criteria (:obj:`StoppingCriteriaList`, `optional`):
                An instance of :class:`~transformers.StoppingCriteriaList`. List of instances of class derived from
                :class:`~transformers.StoppingCriteria` used to tell if the generation loop should stop.
            max_length (:obj:`int`, `optional`, defaults to 20):
                **DEPRECATED**. Use :obj:`logits_processor` or :obj:`stopping_criteria` directly to cap the number of
                generated tokens. The maximum length of the sequence to be generated.
            pad_token_id (:obj:`int`, `optional`):
                The id of the `padding` token.
            eos_token_id (:obj:`int`, `optional`):
                The id of the `end-of-sequence` token.
            output_attentions (:obj:`bool`, `optional`, defaults to `False`):
                Whether or not to return the attentions tensors of all attention layers. See ``attentions`` under
                returned tensors for more details.
            output_hidden_states (:obj:`bool`, `optional`, defaults to `False`):
                Whether or not to return trhe hidden states of all layers. See ``hidden_states`` under returned tensors
                for more details.
            output_scores (:obj:`bool`, `optional`, defaults to `False`):
                Whether or not to return the prediction scores. See ``scores`` under returned tensors for more details.
            return_dict_in_generate (:obj:`bool`, `optional`, defaults to `False`):
                Whether or not to return a :class:`~transformers.file_utils.ModelOutput` instead of a plain tuple.
            synced_gpus (:obj:`bool`, `optional`, defaults to :obj:`False`):
                Whether to continue running the while loop until max_length (needed for ZeRO stage 3)
            model_kwargs:
                Additional model specific kwargs will be forwarded to the :obj:`forward` function of the model. If
                model is an encoder-decoder model the kwargs should include :obj:`encoder_outputs`.
        Return:
            :class:`~transformers.generation_utilsBeamSearchDecoderOnlyOutput`,
            :class:`~transformers.generation_utils.BeamSearchEncoderDecoderOutput` or obj:`torch.LongTensor`: A
            :obj:`torch.LongTensor` containing the generated tokens (default behaviour) or a
            :class:`~transformers.generation_utils.BeamSearchDecoderOnlyOutput` if
            ``model.config.is_encoder_decoder=False`` and ``return_dict_in_generate=True`` or a
            :class:`~transformers.generation_utils.BeamSearchEncoderDecoderOutput` if
            ``model.config.is_encoder_decoder=True``.
        Examples::
            >>> from transformers import (
            ...    AutoTokenizer,
            ...    AutoModelForSeq2SeqLM,
            ...    LogitsProcessorList,
            ...    MinLengthLogitsProcessor,
            ...    BeamSearchScorer,
            ... )
            >>> import torch
            >>> tokenizer = AutoTokenizer.from_pretrained("t5-base")
            >>> model = AutoModelForSeq2SeqLM.from_pretrained("t5-base")
            >>> encoder_input_str = "translate English to German: How old are you?"
            >>> encoder_input_ids = tokenizer(encoder_input_str, return_tensors="pt").input_ids
            >>> # lets run beam search using 3 beams
            >>> num_beams = 3
            >>> # define decoder start token ids
            >>> input_ids = torch.ones((num_beams, 1), device=model.device, dtype=torch.long)
            >>> input_ids = input_ids * model.config.decoder_start_token_id
            >>> # add encoder_outputs to model keyword arguments
            >>> model_kwargs = {
            ...     "encoder_outputs": model.get_encoder()(encoder_input_ids.repeat_interleave(num_beams, dim=0), return_dict=True)
            ... }
            >>> # instantiate beam scorer
            >>> beam_scorer = BeamSearchScorer(
            ...     batch_size=1,
            ...     num_beams=num_beams,
            ...     device=model.device,
            ... )
            >>> # instantiate logits processors
            >>> logits_processor = LogitsProcessorList([
            ...     MinLengthLogitsProcessor(5, eos_token_id=model.config.eos_token_id),
            ... ])
            >>> outputs = model.beam_search(input_ids, beam_scorer, logits_processor=logits_processor, **model_kwargs)
            >>> print("Generated:", tokenizer.batch_decode(outputs, skip_special_tokens=True))
        """
        # init values
        
        logits_processor = logits_processor if logits_processor is not None else LogitsProcessorList()
        stopping_criteria = stopping_criteria if stopping_criteria is not None else StoppingCriteriaList()
        if max_length is not None:
            warnings.warn(
                "`max_length` is deprecated in this function, use `stopping_criteria=StoppingCriteriaList(MaxLengthCriteria(max_length=max_length))` instead.",
                UserWarning,
            )
            stopping_criteria = validate_stopping_criteria(stopping_criteria, max_length)
        if len(stopping_criteria) == 0:
            warnings.warn("You don't have defined any stopping_criteria, this will likely loop forever", UserWarning)
        pad_token_id = pad_token_id if pad_token_id is not None else self.config.pad_token_id
        eos_token_id = eos_token_id if eos_token_id is not None else self.config.eos_token_id
        output_scores = output_scores if output_scores is not None else self.config.output_scores
        output_attentions = output_attentions if output_attentions is not None else self.config.output_attentions
        output_hidden_states = (
            output_hidden_states if output_hidden_states is not None else self.config.output_hidden_states
        )
        return_dict_in_generate = (
            return_dict_in_generate if return_dict_in_generate is not None else self.config.return_dict_in_generate
        )

        # init attention / hidden states / scores tuples
        scores = () if (return_dict_in_generate and output_scores) else None
        decoder_attentions = () if (return_dict_in_generate and output_attentions) else None
        cross_attentions = () if (return_dict_in_generate and output_attentions) else None
        decoder_hidden_states = () if (return_dict_in_generate and output_hidden_states) else None

        # if model is an encoder-decoder, retrieve encoder attention weights and hidden states
        if return_dict_in_generate and self.config.is_encoder_decoder:
            encoder_attentions = model_kwargs["encoder_outputs"].get("attentions") if output_attentions else None
            encoder_hidden_states = (
                model_kwargs["encoder_outputs"].get("hidden_states") if output_hidden_states else None
            )

        batch_size = len(beam_scorer._beam_hyps)
        num_beams = beam_scorer.num_beams

        batch_beam_size, cur_len = input_ids.shape

        assert (
            num_beams * batch_size == batch_beam_size
        ), f"Batch dimension of `input_ids` should be {num_beams * batch_size}, but is {batch_beam_size}."

        beam_scores = torch.zeros((batch_size, num_beams), dtype=torch.float, device=input_ids.device)
        beam_scores[:, 1:] = -1e9
        beam_scores = beam_scores.view((batch_size * num_beams,))

        this_peer_finished = False  # used by synced_gpus only
        logits_recorder = LogitsRecorder(size = input_ids.shape)
        #lm_peaks = torch.zeros(input_ids.shape)
        while True:

            if synced_gpus:
                # Under synced_gpus the `forward` call must continue until all gpus complete their sequence.
                # The following logic allows an early break if all peers finished generating their sequence
                this_peer_finished_flag = torch.tensor(0.0 if this_peer_finished else 1.0).to(input_ids.device)
                # send 0.0 if we finished, 1.0 otherwise
                dist.all_reduce(this_peer_finished_flag, op=dist.ReduceOp.SUM)
                # did all peers finish? the reduced sum will be 0.0 then
                if this_peer_finished_flag.item() == 0.0:
                    break
                
            
            model_inputs = self.model.prepare_inputs_for_generation(input_ids, **model_kwargs)
            outputs = self.model(
                **model_inputs,
                return_dict=True,
                output_attentions=output_attentions,
                output_hidden_states=output_hidden_states,
            )

            if synced_gpus and this_peer_finished:
                cur_len = cur_len + 1
                continue  # don't waste resources running the code we don't need

            next_token_logits = outputs.logits[:, -1, :]
            next_token_logits = self.adjust_logits_during_generation(next_token_logits, cur_len=cur_len)
            next_token_scores = F.log_softmax(next_token_logits, dim=-1)  # (batch_size * num_beams, vocab_size)
            next_token_scores = logits_processor(input_ids, next_token_scores)
            next_token_scores = next_token_scores + beam_scores[:, None].expand_as(next_token_scores)
            logits_list = outputs.lm_logits_individual 
            

            if return_dict_in_generate:
                if output_scores:
                    scores += (next_token_scores,)
                if output_attentions:
                    decoder_attentions += (
                        (outputs.decoder_attentions,) if self.config.is_encoder_decoder else (outputs.attentions,)
                    )
                    if self.config.is_encoder_decoder:
                        cross_attentions += (outputs.cross_attentions,)

                if output_hidden_states:
                    decoder_hidden_states += (
                        (outputs.decoder_hidden_states,)
                        if self.config.is_encoder_decoder
                        else (outputs.hidden_states,)
                    )

            # reshape for beam search
            vocab_size = next_token_scores.shape[-1]
            next_token_scores = next_token_scores.view(batch_size, num_beams * vocab_size)
            next_token_scores_og = next_token_scores
            next_token_scores, next_tokens = torch.topk(
                next_token_scores, 2 * num_beams, dim=1, largest=True, sorted=True
            )
            logit_indices = next_tokens
            next_indices = next_tokens // vocab_size
            next_tokens = next_tokens % vocab_size
            #`print('NEXT TOKENS', next_tokens)
            logits_recorder_outputs = logits_recorder.process(
                input_ids, 
                next_tokens,
                next_indices, 
                logits_list
            )
            
            beam_outputs = beam_scorer.process(
                input_ids,
                next_token_scores,
                next_tokens,
                next_indices,
                pad_token_id=pad_token_id,
                eos_token_id=eos_token_id,
            )
            #print("INPUT IDS", input_ids)
            beam_scores = beam_outputs["next_beam_scores"]
            beam_next_tokens = beam_outputs["next_beam_tokens"]
            beam_idx = beam_outputs["next_beam_indices"]
            input_ids = torch.cat([input_ids[beam_idx, :], beam_next_tokens.unsqueeze(-1)], dim=-1)
            #print("INPUT IDS", input_ids)
            model_kwargs = self._update_model_kwargs_for_generation(
                outputs, model_kwargs, is_encoder_decoder=self.config.is_encoder_decoder
            )
            if model_kwargs["past"] is not None:
                model_kwargs["past"] = self.model._reorder_cache(model_kwargs["past"], beam_idx)

            # increase cur_len
            cur_len = cur_len + 1
            if beam_scorer.is_done or stopping_criteria(input_ids, scores):
                if not synced_gpus:
                    break
                else:
                    this_peer_finished = True

        #print(input_ids)
        sequence_outputs = beam_scorer.finalize(
            input_ids,
            beam_scores,
            next_tokens,
            next_indices,
            pad_token_id=pad_token_id,
            eos_token_id=eos_token_id,
            max_length=stopping_criteria.max_length,
        )
        indices = []
        seq_outputs = sequence_outputs["sequences"][0][:-1]
        
        #if seq_outputs.shape[-1] == 1023:
        #print('SEQUENCES', sequence_outputs, ' '.join([self.tokenizer.decode(w) for w in sequence_outputs["sequences"][0]]))
        seq_len = len(seq_outputs)
        #print(logits_recorder_outputs['beam_ids'])
        
        for i, iid in enumerate(logits_recorder_outputs['beam_ids']):
         #print("COMPARE", seq_outputs.shape[-1], iid.shape)
         iid = iid[:seq_len]
         if iid.shape == seq_outputs.shape:
             #print("COMPARE", seq_outputs, iid)
             #print(iid.eq(seq_outputs))
             #print('-' * 13)
             if torch.all(iid.eq(seq_outputs)):
                indices.append(i)
                break 


        
        if return_dict_in_generate:
            if not output_scores:
                sequence_outputs["sequence_scores"] = None
            if self.config.is_encoder_decoder:
                return BeamSearchEncoderDecoderOutput(
                    sequences=sequence_outputs["sequences"],
                    sequences_scores=sequence_outputs["sequence_scores"],
                    scores=scores,
                    encoder_attentions=encoder_attentions,
                    encoder_hidden_states=encoder_hidden_states,
                    decoder_attentions=decoder_attentions,
                    cross_attentions=cross_attentions,
                    decoder_hidden_states=decoder_hidden_states,
                )
            else:
                return BeamSearchDecoderOnlyOutput(
                    sequences=sequence_outputs["sequences"],
                    sequences_scores=sequence_outputs["sequence_scores"],
                    scores=scores,
                    attentions=decoder_attentions,
                    hidden_states=decoder_hidden_states,
                )
        else:
            logits_scores = logits_recorder_outputs['beam_logits'][indices[0]] if indices != [] else [] 
            return sequence_outputs["sequences"], logits_scores
